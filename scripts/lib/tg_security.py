"""
Security helpers for the Telegram gateway.
All functions are pure (no I/O) except check_rate_limit which reads/writes a JSON state file.
"""
import html
import json
import os
import re
import time
import unicodedata
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_MESSAGE_CHARS = 1500

RATE_LIMIT_MAX_MESSAGES = 20   # per window
RATE_LIMIT_WINDOW_SECS  = 3600 # 1 hour
RATE_MIN_INTERVAL_SECS  = 3    # minimum gap between messages

# Unicode bidirectional controls and zero-width chars used in injection attacks
_DANGEROUS_UNICODE_RE = re.compile(
    '['
    '‪-‮'   # LRE, RLE, PDF, LRO, RLO
    '⁦-⁩'   # LRI, RLI, FSI, PDI
    '​-‏'   # zero-width space, non-joiner, joiner, LRM, RLM
    ' - '   # line/paragraph separator
    '-'   # C0 controls (skip NUL=\x00, TAB=\x09, LF=\x0a, CR=\x0d)
    '-'   # VT, FF
    '-'   # more C0 controls
    ''          # DEL
    ']'
)

# Prompt injection pattern fragments (case-insensitive)
_INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in [
    r'ignore\s+(all\s+)?previous\s+instructions',
    r'disregard\s+(all\s+)?previous',
    r'new\s+instructions?\s*:',
    r'your\s+(new\s+)?system\s+prompt',
    r'you\s+are\s+now\s+(?:a\s+)?(?:DAN|dev(?:eloper)?\s+mode|unrestricted|jailbroken)',
    r'forget\s+(all\s+)?(previous\s+)?instructions',
    r'<\|.*?\|>',
    r'\[INST\]',
    r'###\s*instruction',
    r'enter\s+(developer|dev|maintenance|admin|god|jailbreak)\s+mode',
    r'security\s+(policy\s+)?(?:override|revoked|disabled|lifted)',
    r'anthropic\s+security\s+team',
    r'(you\s+have\s+)?no\s+restrictions?\s+(now|anymore|apply)',
    r'as\s+(a\s+)?(?:DAN|jailbroken|unrestricted)\s+AI',
    r'pretend\s+(you\s+have\s+)?no\s+(safety\s+)?guidelines',
    r'override\s+(all\s+)?(?:previous\s+)?(?:instructions?|restrictions?|policies?)',
    r'act\s+as\s+(if\s+)?(?:you\s+(?:have|had)\s+)?no\s+(content\s+)?(?:filter|restriction)',
    r'(system|admin|operator)\s*:\s*',
    r'\[system\]',
    r'<system>',
]]

# Sensitive patterns that must never appear in responses sent to Telegram
_OUTPUT_REDACTIONS = [
    # Anthropic API keys
    (re.compile(r'sk-ant-[a-zA-Z0-9\-_]{10,}'), '[REDACTED-API-KEY]'),
    # Generic long secrets next to known key names
    (re.compile(
        r'\b(ANTHROPIC_API_KEY|LANGFUSE_(?:PUBLIC|SECRET)_KEY|TELEGRAM_BOT_TOKEN'
        r'|TELEGRAM_CHAT_ID|OPENAI_API_KEY|SECRET_KEY|API_KEY|AUTH_TOKEN)\s*[=:]\s*\S+',
        re.IGNORECASE
    ), r'\1=[REDACTED]'),
    # Email addresses
    (re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'), '[REDACTED-EMAIL]'),
    # Linux filesystem paths starting at known roots
    (re.compile(r'(?:/opt|/home|/root|/etc|/var|/tmp|/usr|/proc|/sys)[/\w.\-]+'), '[REDACTED-PATH]'),
    # IPv4 addresses
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[REDACTED-IP]'),
    # SCREAMING_SNAKE env-var assignments
    (re.compile(r'\b([A-Z][A-Z0-9_]{3,})\s*=\s*\S+'), r'\1=[REDACTED]'),
]

# Safe skill name: alphanumeric, hyphens, underscores; no dots, slashes, or traversal
_SAFE_SKILL_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$')

# ── Functions ──────────────────────────────────────────────────────────────────

def sanitize_input(text: str) -> tuple:
    """
    Sanitize a Telegram message before it reaches Claude.

    Returns (cleaned_text, None) if the message is acceptable.
    Returns (None, error_str) if the message should be rejected.
    error_str is safe to send directly to the user.
    """
    # Strip dangerous Unicode control / bidi characters
    text = _DANGEROUS_UNICODE_RE.sub('', text)

    # Normalize to NFC to defeat homoglyph substitution tricks
    text = unicodedata.normalize('NFC', text)

    # Length cap
    if len(text) > MAX_MESSAGE_CHARS:
        return None, f"⚠️ Message too long (max {MAX_MESSAGE_CHARS} characters)."

    # Injection pattern check
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return None, "⚠️ I can't process that message."

    return text, None


def scan_output(text: str) -> str:
    """
    Redact sensitive patterns from Claude's response before it is sent to Telegram.
    All replacements are annotated so the user knows redaction occurred.
    """
    for pattern, replacement in _OUTPUT_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def escape_html_response(text: str) -> str:
    """
    HTML-escape Claude's response so attacker-influenced markup cannot render.
    Use this before calling tg_send(response) with parse_mode='HTML'.
    """
    return html.escape(text)


def validate_skill_name(name: str) -> bool:
    """
    Return True iff name is safe to interpolate into filesystem paths.
    Rejects: empty, path separators, parent traversal, leading dots, too long.
    """
    if not name:
        return False
    if '/' in name or '\\' in name or '..' in name or name.startswith('.'):
        return False
    return bool(_SAFE_SKILL_NAME_RE.match(name))


def check_rate_limit(chat_id: str, state_file: str) -> tuple:
    """
    Enforce per-chat rate limiting using a JSON state file.

    Returns (True, None) if the message is allowed and updates the state file.
    Returns (False, error_str) if the message should be dropped.
    """
    now = time.time()
    state: dict = {}

    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
        except Exception:
            state = {}

    user = state.get(str(chat_id), {'timestamps': []})
    # Drop timestamps outside the window
    timestamps = [t for t in user.get('timestamps', []) if now - t < RATE_LIMIT_WINDOW_SECS]

    # Minimum inter-message interval
    if timestamps and (now - timestamps[-1]) < RATE_MIN_INTERVAL_SECS:
        return False, "⚠️ Please wait a moment before sending another message."

    # Hourly cap
    if len(timestamps) >= RATE_LIMIT_MAX_MESSAGES:
        remaining = int(RATE_LIMIT_WINDOW_SECS - (now - timestamps[0]))
        return False, f"⚠️ Message limit reached. Try again in {remaining // 60} minutes."

    timestamps.append(now)
    state[str(chat_id)] = {'timestamps': timestamps}

    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
    except Exception:
        pass  # Non-fatal: rate limit silently passes on write failure

    return True, None
