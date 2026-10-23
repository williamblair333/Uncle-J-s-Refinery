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

# Exclusive file locking, portably. fcntl is POSIX-only; on Windows the stdlib
# equivalent is msvcrt.locking, which needs a non-empty byte range to lock.
# Importing fcntl unconditionally made this module — and therefore the whole test
# suite, which imports it at collection time — fail to load on Windows.
try:
    import fcntl as _fcntl

    _msvcrt = None
except ImportError:  # Windows
    _fcntl = None
    import msvcrt as _msvcrt


def _lock_exclusive(fh) -> bool:
    """Take an exclusive lock on an open file handle. Returns True if acquired.

    Best-effort by design: check_rate_limit already fails open on read/write
    errors, so a lock we cannot take must not raise and block a legitimate
    message. Note msvcrt.locking gives up after ~10s where flock waits forever.
    """
    try:
        if _fcntl is not None:
            _fcntl.flock(fh, _fcntl.LOCK_EX)
        else:
            fh.write('\0')  # msvcrt cannot lock a zero-length range
            fh.flush()
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_LOCK, 1)
        return True
    except OSError:
        return False


def _unlock(fh, locked: bool) -> None:
    if not locked:
        return
    try:
        if _fcntl is not None:
            _fcntl.flock(fh, _fcntl.LOCK_UN)
        else:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)
    except OSError:
        pass

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_MESSAGE_CHARS = 1500

RATE_LIMIT_MAX_MESSAGES = 20   # per window
RATE_LIMIT_WINDOW_SECS  = 3600 # 1 hour
RATE_MIN_INTERVAL_SECS  = 3    # minimum gap between messages

# Unicode bidirectional controls and zero-width chars used in injection attacks
_DANGEROUS_UNICODE_RE = re.compile(
    '['
    '\u202a-\u202e'   # LRE, RLE, PDF, LRO, RLO (bidi embedding/override)
    '\u2066-\u2069'   # LRI, RLI, FSI, PDI (isolate controls)
    '\u200b-\u200f'   # zero-width space, non-joiner, joiner, LRM, RLM
    '\u2028-\u2029'   # line separator, paragraph separator
    '\x01-\x08'       # C0 controls (skip NUL=\x00, TAB=\x09, LF=\x0a)
    '\x0b-\x0c'       # VT, FF
    '\x0e-\x1f'       # more C0 controls (skip CR=\x0d)
    '\x7f'            # DEL
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
    r'(?:^|\n)\s*(system|admin|operator)\s*:\s*',   # fake role prefix at line start
    r'\[system\]',
    r'<system>',
]]

# A value that looks like a secret: 12+ non-space chars with at least one digit.
# ("required", "configured" and other prose after "API key is" never qualify.)
_SECRETISH = r'[`"\']?(?=[^\s`"\']*\d)[^\s`"\'<>]{12,}'

# Sensitive patterns that must never appear in responses sent to Telegram
_OUTPUT_REDACTIONS = [
    # ── 2026-10-23: token SHAPES, whatever (if anything) names them ──
    # Telegram bot token <bot-id>:<35 urlsafe> — the gateway's own credential.
    (re.compile(r'\b\d{6,12}:[A-Za-z0-9_-]{30,}'), '[REDACTED-TOKEN]'),
    # GitHub / Gitea-style, OpenAI-style, Langfuse, AWS, Slack, Google, JWT, PEM.
    (re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'), '[REDACTED-TOKEN]'),
    (re.compile(r'(?<![a-zA-Z])sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}'), '[REDACTED-API-KEY]'),
    (re.compile(r'\b(?:pk|sk)-lf-[A-Za-z0-9\-]{8,}'), '[REDACTED-API-KEY]'),
    (re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'), '[REDACTED-API-KEY]'),
    (re.compile(r'\bxox[abposr]-[A-Za-z0-9\-]{10,}'), '[REDACTED-TOKEN]'),
    (re.compile(r'\bAIza[0-9A-Za-z_\-]{35}'), '[REDACTED-API-KEY]'),
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}'), '[REDACTED-TOKEN]'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE[ ]KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE[ ]KEY-----|$)'),
     '[REDACTED-PRIVATE-KEY]'),
    (re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{16,}'), 'Bearer [REDACTED]'),
    # Spaced / lower-case / prose key names ("telegram bot token is 123…",
    # "api key: abc123…", "password = hunter2hunter2") the SCREAMING_SNAKE rules miss.
    (re.compile(
        r'(?i)\b((?:telegram[\s_\-]*bot[\s_\-]*token|bot[\s_\-]*token|anthropic[\s_\-]*api[\s_\-]*key'
        r'|openai[\s_\-]*api[\s_\-]*key|api[\s_\-]*key|secret[\s_\-]*key|client[\s_\-]*secret'
        r'|access[\s_\-]*token|auth[\s_\-]*token|refresh[\s_\-]*token|private[\s_\-]*key'
        r'|password|passwd|passphrase|chat[\s_\-]*id)'
        r'(?:\s+(?:is|was|value|of)\b)*\s*(?:[=:]|->|is|equals)?\s*)' + _SECRETISH),
     r'\1[REDACTED]'),
    # Anthropic API keys. (?<![a-zA-Z]) stops "task-ant-…"/"flask-ant-…" from matching
    # the trailing "sk" of an ordinary hyphenated word (false-positive over-redaction).
    (re.compile(r'(?<![a-zA-Z])sk-ant-[a-zA-Z0-9\-_]{10,}'), '[REDACTED-API-KEY]'),
    # Generic long secrets next to known key names
    (re.compile(
        r'\b(ANTHROPIC_API_KEY|LANGFUSE_(?:PUBLIC|SECRET)_KEY|TELEGRAM_BOT_TOKEN'
        r'|TELEGRAM_CHAT_ID|OPENAI_API_KEY|SECRET_KEY|API_KEY|AUTH_TOKEN)\s*[=:]\s*\S+',
        re.IGNORECASE
    ), r'\1=[REDACTED]'),
    # Email addresses
    (re.compile(r'\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b'), '[REDACTED-EMAIL]'),
    # Linux filesystem paths starting at known roots
    (re.compile(r'(?:/opt|/home|/root|/etc|/var|/tmp|/usr|/proc|/sys|/run|/mnt|/srv|/dev|/snap|/media)[/\w.\-]+'), '[REDACTED-PATH]'),
    # Relative dotenv/secret-file references the absolute-path rule above misses
    # (./.env, config/.env, bare .env). "environment" is unaffected — a literal dot is required.
    (re.compile(r'(?:[\w.\-/]*/)?\.env(?:\.\w+)?\b'), '[REDACTED-PATH]'),
    # Spaced/separated Anthropic key (sk - ant - …) the contiguous rule above misses.
    # The (?<![a-zA-Z]) left-guard stops "task-ant-…"/"flask-ant-…" from matching the
    # trailing "sk" of an ordinary word (would over-redact / falsely reject a skill).
    # Prose-spelled keys ("es kay dash ant") remain inherent and are an accepted residual.
    (re.compile(r'(?<![a-zA-Z])sk[\s\-]+ant[\s\-]+[a-zA-Z0-9]{12,}'), '[REDACTED-API-KEY]'),
    # IPv4 addresses
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[REDACTED-IP]'),
    # SCREAMING_SNAKE env-var assignments
    (re.compile(r'\b([A-Z][A-Z0-9_]{3,})\s*=\s*\S+'), r'\1=[REDACTED]'),
]

# Output-only: host paths the absolute-root rule above misses. NOT applied to skill
# drafts (scan_skill_body) — a skill legitimately says "run scripts/x.sh".
_OUTPUT_ONLY_REDACTIONS = [
    # ~/… home paths (the guard list matched only absolute roots)
    (re.compile(r'(?<![\w/])~/[^\s`"\'<>)\]]+'), '[REDACTED-PATH]'),
    # Windows and MSYS spellings: C:\Users\…, /c/opt/proj/…
    (re.compile(r'\b[A-Za-z]:\\[^\s`"\'<>]+'), '[REDACTED-PATH]'),
    (re.compile(r'(?<![\w.:/])/[a-z]/(?:opt|home|Users|Program Files|Windows)[^\s`"\'<>]*'), '[REDACTED-PATH]'),
    # Relative paths naming a file (dir/…/name.ext). The left guard keeps URL paths
    # (https://host/a/b.md) out: a match can't start after / . : ~ or a word char.
    (re.compile(r'(?<![\w/:.~\-])(?:\.{1,2}/)?(?:[\w.\-]+/)+[\w.\-]+\.(?:py|sh|bash|toml|ya?ml|json|jsonl|md'
                r'|txt|log|env|cfg|ini|conf|js|mjs|ts|sqlite|db|lock|key|pem|crt|service|timer)\b'),
     '[REDACTED-PATH]'),
    # This stack's own directories, with or without a file after them.
    (re.compile(r'(?<![\w/:.~\-])(?:\./)?(?:scripts|state|config|hooks|features|global-skills|\.claude'
                r'|\.uncle-j-memory|review|lib)/[\w./\-]*'), '[REDACTED-PATH]'),
]

# Skill frontmatter keys that grant the skill power when it is invoked: pre-approved
# tools, shell hooks, a forked agent context. A promoted draft must never carry them
# (red-team 2026-10-23: the description was scanned, the keys were not).
_FORBIDDEN_FRONTMATTER_KEYS = {
    'allowed-tools', 'allowed_tools', 'hooks', 'context', 'agent', 'permissionmode',
    'permission-mode', 'permission_mode',
}
# `!`cmd`` in a skill body is run by Claude Code when the skill loads.
_SKILL_SHELL_INJECTION_RE = re.compile(r'!\s*`')

# Safe skill name: alphanumeric, hyphens, underscores; no dots, slashes, or traversal
_SAFE_SKILL_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$')

# ── Functions ──────────────────────────────────────────────────────────────────

def sanitize_input(text: str) -> 'tuple[str | None, str | None]':
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
    for pattern, replacement in _OUTPUT_REDACTIONS + _OUTPUT_ONLY_REDACTIONS:
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


def scan_skill_body(path: str) -> 'tuple[bool, str | None]':
    """
    Scan a skill draft file for injection patterns and secrets before promotion.

    Injection AND secret patterns are checked against the WHOLE file, frontmatter
    included. The frontmatter `description:` is loaded by Claude in future sessions,
    so an injection hidden there is a persistent, cross-session attack vector
    (red-team HIGH) — scanning the body only let it through. The specific injection
    regexes (e.g. "ignore previous instructions", "system:" line-prefix) do not
    match the bare word "instructions", so legitimate descriptions still pass.

    Returns (True, None) if safe, (False, reason_str) if rejected.
    """
    try:
        with open(path, encoding='utf-8') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return False, f"Could not read draft: {type(e).__name__}"

    # 2026-10-23: the regexes ran on the RAW text, so a zero-width or bidi character
    # inside a phrase ("ignore<U+200B> previous instructions") or fullwidth letters
    # slipped past every pattern while reading the same to Claude. Scan the raw text
    # AND two normalisations: dangerous characters deleted, and replaced by a space,
    # both NFKC-folded (fullwidth → ASCII). A hit in any variant rejects.
    variants = [content]
    for repl in ('', ' '):
        variants.append(unicodedata.normalize('NFKC', _DANGEROUS_UNICODE_RE.sub(repl, content)))
    if any(_DANGEROUS_UNICODE_RE.search(v) for v in variants[:1]):
        return False, "Skill file contains invisible or bidi control characters."

    # Whole file: check for prompt injection patterns (frontmatter included)
    for pattern in _INJECTION_PATTERNS:
        if any(pattern.search(v) for v in variants):
            return False, "Skill file contains injection pattern."

    # Frontmatter: keys that grant power when the skill runs.
    fm = re.match(r'\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)', content, re.S)
    if fm:
        for line in fm.group(1).splitlines():
            m = re.match(r'^\s*["\']?([A-Za-z_][A-Za-z0-9_\-]*)["\']?\s*:', line)
            if m and m.group(1).lower() in _FORBIDDEN_FRONTMATTER_KEYS:
                return False, f"Skill frontmatter key not allowed: {m.group(1)}"
    elif content.lstrip().startswith('---'):
        return False, "Skill frontmatter is malformed."

    # `!`cmd`` runs a shell command when the skill is loaded.
    if any(_SKILL_SHELL_INJECTION_RE.search(v) for v in variants):
        return False, "Skill file contains a shell-execution (!`cmd`) block."

    # Whole file: check for secrets (API keys, env var assignments, etc.)
    for pattern, _ in _OUTPUT_REDACTIONS:
        if any(pattern.search(v) for v in variants):
            return False, "Skill file contains sensitive data pattern."

    return True, None


def assert_skill_target_safe(link_path: str) -> None:
    """
    Guard against the destructive `promote` rmtree (red-team MEDIUM).

    The gateway only ever installs skills as symlinks into ~/.claude/skills. A real
    directory or file at the target means a legitimate, non-gateway skill lives there;
    overwriting it (the old `shutil.rmtree` path) would destroy it on a name collision.

    Raises ValueError if `link_path` exists and is NOT a symlink. A missing path or a
    gateway-owned symlink is safe to (re)create.
    """
    if os.path.islink(link_path):
        return
    if os.path.exists(link_path):
        raise ValueError(
            f"refusing to overwrite non-symlink at {link_path} — "
            f"a real skill of this name already exists"
        )


def assert_skill_install_safe(skill_dir: str, draft_path: str, link_path: str) -> None:
    """
    Refuse a promotion that would destroy or hijack an existing skill (red-team
    2026-10-23, the part of the promote-collision finding assert_skill_target_safe
    left open).

    * skill_dir exists → it must be a real directory whose SKILL.md is byte-identical
      to the draft. That is the auto-maintain Part C case: an untracked
      global-skills/<name>/SKILL.md drafted for approval. Anything else — a different
      skill of the same name — was silently overwritten by shutil.copy2 (a draft
      named `pre-mortem` replaced that skill's SKILL.md, and with it the gate).
    * link_path is a symlink → it must already point at skill_dir. Every symlink was
      treated as "gateway-owned", so a draft could re-point the link of a skill that
      lives elsewhere (a plugin, another repo, the other scope).

    Raises ValueError on refusal; returns None when the install is safe.
    """
    if os.path.lexists(skill_dir):
        if os.path.islink(skill_dir) or not os.path.isdir(skill_dir):
            raise ValueError(f"refusing: {skill_dir} exists and is not a plain directory")
        existing = os.path.join(skill_dir, 'SKILL.md')
        if os.path.lexists(existing):
            if os.path.islink(existing) or not os.path.isfile(existing):
                raise ValueError(f"refusing: {existing} is not a regular file")
            with open(existing, 'rb') as a, open(draft_path, 'rb') as b:
                if a.read() != b.read():
                    raise ValueError(f"refusing to overwrite a different skill at {skill_dir}")
        elif os.listdir(skill_dir):
            raise ValueError(f"refusing: {skill_dir} exists and holds other files")
    if os.path.islink(link_path):
        if os.path.realpath(link_path) != os.path.realpath(skill_dir):
            raise ValueError(f"refusing: {link_path} points at a different skill")


# Built-in tools the untrusted (restricted) agent must never reach: execution,
# persistence, network, file read, and sub-agent spawning.
_RESTRICTED_DENY_TOOLS = [
    "Bash", "Edit", "Write", "NotebookEdit",
    "WebFetch", "WebSearch", "Read", "Grep", "Glob", "Task",
]


def build_claude_argv(claude_bin: str, agent_sp: str,
                      system_restriction: str, routed_text: str) -> list:
    """
    Construct the `claude` CLI argv for a Telegram agent invocation.

    The 'restricted' agent serves an UNTRUSTED Telegram channel and runs with no
    host access, enforced by three independent default-deny layers:
      1. NO --dangerously-skip-permissions — headless --print cannot answer a
         permission prompt, so any approval-gated tool (incl. future ones) is denied.
      2. --strict-mcp-config (with no --mcp-config) — no MCP servers load, so the
         retrieval stack (jcodemunch/jdata/jdoc/etc.) is unavailable.
      3. --disallowedTools — dangerous built-ins are removed from context outright.

    Any other agent (e.g. the trusted /work agent, system_prompt != "restricted")
    keeps full access; it is gated upstream by the chat_id allowlist.

    `routed_text` is always the value of the final `-p` flag — never interpolated
    into other flags — so a hostile message cannot inject CLI arguments.
    """
    if agent_sp == "restricted":
        return [
            claude_bin,
            "--print",
            "--system-prompt", system_restriction,
            "--strict-mcp-config",
            "--disallowedTools", *_RESTRICTED_DENY_TOOLS,
            "-p", routed_text,
        ]
    return [
        claude_bin,
        "--dangerously-skip-permissions",
        "--print",
        "-p", routed_text,
    ]


def record_stack_callback(state_path: str, message_id: int, data: str) -> None:
    """
    Record a stack-alert approve/skip button press for the stack-alerts poller to read.

    The Telegram gateway is the SOLE getUpdates consumer (single-consumer-per-token —
    a second no-offset consumer corrupted the shared update offset, incident F1/F2/F3).
    The gateway drains the callback_query and writes the decision here; the stack-alerts
    poller reads it via read_stack_callback() instead of making its own getUpdates call.

    Write is atomic (temp + os.replace) so a concurrent reader never sees a partial file.
    """
    tmp = state_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump({"message_id": int(message_id), "data": str(data)}, f)
    os.replace(tmp, state_path)


_SCOUT_CALLBACK_RE = re.compile(
    r'scout:(yes|maybe|no|e-yes|e-maybe|e-no|r-have|r-goals|r-heavy|r-later):\d{1,20}')


def record_scout_callback(state_path: str, message_id: int, data: str) -> bool:
    """
    Record a repo-scout button press for the scout's next run to apply.

    Unlike stack alerts, the scout needs every tap in order ("no", then a reason), so
    this appends one JSON line per tap rather than overwriting. The scout renames the
    file aside before reading it, so an append racing a read lands in a fresh file.
    Returns False, writing nothing, when data isn't a well-formed scout callback.
    """
    if not isinstance(data, str) or not _SCOUT_CALLBACK_RE.fullmatch(data):
        return False
    line = json.dumps({"message_id": int(message_id), "data": data, "ts": int(time.time())})
    with open(state_path, 'a') as f:
        f.write(line + "\n")
    return True


def scout_reason_keyboard(repo_id: int) -> str:
    """Inline keyboard asking why a scout find was turned down."""
    rid = int(repo_id)
    return json.dumps([
        [{"text": "Already have it", "callback_data": f"scout:r-have:{rid}"},
         {"text": "Not my goals", "callback_data": f"scout:r-goals:{rid}"}],
        [{"text": "Too heavy", "callback_data": f"scout:r-heavy:{rid}"},
         {"text": "Not now", "callback_data": f"scout:r-later:{rid}"}],
    ])


def read_stack_callback(state_path: str, target_message_id: int) -> str:
    """
    Read (and on match, consume) the recorded stack-alert callback.

    Returns "approved" if the recorded decision for target_message_id is "approve",
    "rejected" for any other recorded decision, or "pending" if there is no file, the
    file is malformed, or the recorded message_id does not match target. A non-matching
    poll never consumes the file, so a live callback for a different message survives.
    """
    if not os.path.exists(state_path):
        return "pending"
    try:
        with open(state_path) as f:
            d = json.load(f)
    except Exception:
        return "pending"
    if int(d.get("message_id", -1)) != int(target_message_id):
        return "pending"
    decision = d.get("data", "")
    try:
        os.remove(state_path)  # consume on match
    except OSError:
        pass
    return "approved" if decision == "approve" else "rejected"


def check_rate_limit(chat_id: str, state_file: str) -> tuple:
    """
    Enforce per-chat rate limiting using a JSON state file.

    Returns (True, None) if the message is allowed and updates the state file.
    Returns (False, error_str) if the message should be dropped.
    """
    now = time.time()
    state: dict = {}

    lock_path = state_file + '.lock'
    with open(lock_path, 'w') as lock_fd:
        _locked = _lock_exclusive(lock_fd)
        try:
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                except Exception:
                    state = {}

            user = state.get(str(chat_id), {'timestamps': []})
            timestamps = [t for t in user.get('timestamps', []) if now - t < RATE_LIMIT_WINDOW_SECS]

            if timestamps and (now - timestamps[-1]) < RATE_MIN_INTERVAL_SECS:
                return False, "⚠️ Please wait a moment before sending another message."

            if len(timestamps) >= RATE_LIMIT_MAX_MESSAGES:
                remaining = max(0, int(RATE_LIMIT_WINDOW_SECS - (now - timestamps[0])))
                return False, f"⚠️ Message limit reached. Try again in {remaining // 60} minutes."

            timestamps.append(now)
            state[str(chat_id)] = {'timestamps': timestamps}

            try:
                with open(state_file, 'w') as f:
                    json.dump(state, f)
            except Exception:
                pass  # Fails open — caller can still proceed; log externally if needed

            return True, None
        finally:
            _unlock(lock_fd, _locked)
