#!/usr/bin/env python3
"""Stop hook: steps for someone else's product must be current, and must come with a CLI route.

Two failures it catches, both raised by Bill on 2026-11-14:
  1. Stale steps. Claude gives click-paths for a vendor console ("click Get started") from
     training memory; the console changed since, and Bill wastes time hunting a button that
     isn't there. Rule: such steps come from a page fetched this turn (WebFetch / WebSearch /
     context7), cited with its URL, or are labelled "from memory".
  2. GUI only. Bill would rather not click through a console when a command line exists.
     Rule: every set of GUI steps names the CLI way too, or says no CLI exists and how one
     could be written (API + script).

Reads the hook JSON on stdin, looks at the turn that just ended (assistant text plus the
tools it called) and blocks the stop once with what is missing. `stop_hook_active` means this
is the reply the hook forced, so it never blocks twice. Quoted material (code, blockquotes,
short "quoted" phrases) doesn't count as steps.

Kill switch: UI_STEPS_SCAN=off. Skipped for `claude -p` (sdk entrypoints). Hits are logged
(cwd and which rule, no content) to ~/.claude/state/ui-steps-scan.jsonl.
Bench: python3 scripts/ui_steps_scan.py --replay [--days N] [--files ...]
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workaround_scan import _is_prompt, _tail_lines, _texts  # noqa: E402

# Wording that gives GUI steps: a button or menu to click, a menu path, a console URL.
UI_PATTERNS = [
    # "click **Save**", "click Get started", "press the Create button"
    # (keyboard keys are terminal or BIOS steps, not a vendor GUI)
    r"\b(?:[Cc]lick|[Tt]ap|[Pp]ress)\s+(?:on\s+)?(?:the\s+)?(?:\*\*|\")?"
    r"(?!(?:Enter|Return|Tab|Esc|Escape|Del|Delete|Space|Ctrl|Alt|Shift|F\d+)\b)[A-Z][\w-]*",
    # menu paths of 3+ levels: "Settings → Devices & services → Helpers". Two levels and
    # ALL-CAPS words are prose ("Gitea → GitHub mirror", "MCP → CLI → MCP").
    r"\b(?![A-Z]{2,}\b)[A-Z][a-z][\w&]*(?: [\w&]+){0,3} (?:>|→|») (?:\*\*)?(?![A-Z]{2,}\b)[A-Z][a-z][\w&]*"
    r"(?: [\w&]+){0,3}(?:\*\*)? (?:>|→|») (?:\*\*)?[A-Z]",
    r"\b(?:in|from|open) the (?:left|right|top|side)[- ]?(?:hand )?(?:nav(?:igation)?|menu|sidebar|panel)\b",
    r"\b[Ss]elect\b[^.\n]{0,40}\bfrom the (?:drop-?down|menu)\b",
]
# vendor consoles and settings pages
_VENDOR = (r"https?://(?:console\.cloud\.google|console\.aws\.amazon|portal\.azure|dash\.cloudflare"
           r"|console\.firebase\.google|app\.netlify|vercel\.com/dashboard|github\.com/settings"
           r"|myaccount\.google|admin\.google|console\.anthropic|platform\.openai)\S*")
_VENDOR_RE = re.compile(_VENDOR)
_UI_RE = re.compile("|".join(f"(?:{p})" for p in UI_PATTERNS + [_VENDOR]))
# Our own pages (local web UIs): no web page to look the steps up on.
_LOCAL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0|192\.168\.)\S*")

# A turn that names a CLI route, or says there is none.
_CLI_RE = re.compile(r"\bCLI\b|\bcommand[- ]line\b", re.I)
# A turn that labels its steps as recalled, not looked up.
_MEMORY_RE = re.compile(r"\bfrom memory\b|\bnot (?:looked up|verified)\b|\bunverified\b", re.I)
# Tools that fetch a current page.
FRESH_TOOLS = {"WebFetch", "WebSearch", "mcp__context7__query-docs", "mcp__context7__resolve-library-id"}

_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`|\"[^\"\n]{1,60}\"|“[^”\n]{1,60}”", re.S)
_QUOTE_RE = re.compile(r"^\s*>.*$", re.M)

LOG = Path(os.environ.get("UI_STEPS_SCAN_LOG")
           or Path.home() / ".claude" / "state" / "ui-steps-scan.jsonl")


def all_turns(transcript: Path) -> list[dict]:
    """Every turn as {'text': assistant text, 'tools': tool names called}."""
    entries = []
    try:
        for line in _tail_lines(transcript):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    turns = []
    cur = {"text": [], "tools": set()}
    started = False
    for e in entries:
        if _is_prompt(e):
            if started or cur["text"]:
                turns.append(cur)
            cur = {"text": [], "tools": set()}
            started = True
        elif e.get("type") == "assistant":
            content = (e.get("message") or {}).get("content")
            cur["text"].extend(_texts(content))
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    cur["tools"].add(c.get("name", ""))
    if started or cur["text"]:
        turns.append(cur)
    return [{"text": "\n".join(t["text"]), "tools": t["tools"]} for t in turns]


def ui_hits(text: str) -> list[str]:
    """GUI-step wording in text, with a little context; quoted material removed."""
    text = _QUOTE_RE.sub("", _CODE_RE.sub("", _LOCAL_RE.sub("", text)))
    hits = []
    for m in _UI_RE.finditer(text):
        a, b = max(0, m.start() - 50), min(len(text), m.end() + 50)
        hits.append(" ".join(text[a:b].split()))
    return hits


def check(text: str, tools: set) -> tuple[list[str], list[str]]:
    """(hits, missing rules). Needs 2+ hits so one stray 'click' doesn't count as steps."""
    hits = ui_hits(text)
    if len(hits) < 2:
        return hits, []
    missing = []
    # Steps for our own local page can't be looked up on the web; the CLI rule still applies.
    own_page = _LOCAL_RE.search(text) and not _VENDOR_RE.search(text)
    if not own_page and not (tools & FRESH_TOOLS) and not _MEMORY_RE.search(text):
        missing.append("fresh")
    if not _CLI_RE.search(text):
        missing.append("cli")
    return hits, missing


def decide(hook: dict) -> dict | None:
    if hook.get("stop_hook_active") or os.environ.get("UI_STEPS_SCAN") == "off":
        return None
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return None
    path = hook.get("transcript_path")
    turns = all_turns(Path(path)) if path else []
    turn = turns[-1] if turns else {"text": hook.get("last_assistant_message") or "", "tools": set()}
    hits, missing = check(turn["text"], turn["tools"])
    if not missing:
        return None
    shown = "\n".join(f"  - …{h}…" for h in hits[:3])
    asks = []
    if "fresh" in missing:
        asks.append("These steps weren't looked up this turn. Fetch the vendor's current page "
                    "(WebFetch/WebSearch/context7), fix the steps to match it and cite the URL "
                    "and its last-updated date. If you can't, label them \"from memory, may be "
                    "out of date\".")
    if "cli" in missing:
        asks.append("Give the CLI way too (a `CLI:` line with the exact command, checked with "
                    "`--help` where it's installed). If no CLI exists, say so and sketch how to "
                    "write one (the API it would call, a script with --check/--fix per "
                    "docs/TOOLS-STANDARD.md).")
    return {"decision": "block", "missing": missing, "reason": (
        "UI-steps check: this turn gives GUI steps for someone else's product.\n"
        f"{shown}\n" + "\n".join(asks) +
        "\nIf these aren't vendor GUI steps, say so in one line.")}


def _log(hook: dict, missing: list[str]) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), "cwd": hook.get("cwd"),
                                "missing": missing}) + "\n")
    except OSError:
        pass


def replay(paths) -> dict:
    res = {"turns": 0, "fired": 0, "fresh": 0, "cli": 0, "hits": []}
    for p in paths:
        path = Path(p)
        if not path.is_file():
            continue
        for t in all_turns(path):
            res["turns"] += 1
            hits, missing = check(t["text"], t["tools"])
            if missing:
                res["fired"] += 1
                for m in missing:
                    res[m] += 1
                res["hits"].append({"file": str(path), "missing": missing, "snippet": hits[0]})
    return res


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--replay" in argv:
        ap = argparse.ArgumentParser(description="UI-steps check replay bench")
        ap.add_argument("--replay", action="store_true")
        ap.add_argument("--files", nargs="+", type=Path)
        ap.add_argument("--days", type=int, default=7)
        ap.add_argument("--limit", type=int, default=20)
        args = ap.parse_args(argv)
        if args.files:
            files = args.files
        else:
            cutoff = time.time() - args.days * 86400
            projects = Path.home() / ".claude" / "projects"
            files = [p for p in projects.glob("*/*.jsonl") if p.stat().st_mtime >= cutoff] \
                if projects.exists() else []
        res = replay(files)
        pct = res["fired"] / res["turns"] * 100 if res["turns"] else 0.0
        print(f"fired on {res['fired']}/{res['turns']} turns ({pct:.1f}%) across {len(files)} files"
              f" — not fresh: {res['fresh']}, no CLI: {res['cli']}")
        for h in res["hits"][:args.limit]:
            print(f"{h['file']} [{','.join(h['missing'])}]: …{h['snippet']}…")
        return 0
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    verdict = decide(hook)
    if verdict:
        _log(hook, verdict.pop("missing"))
        print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
