#!/usr/bin/env python3
"""PreToolUse (Bash) hook: a big download waits until an alternatives scan covers it.

2026-11-02: Strata's 64 GB model was downloaded and benched for a day before anyone looked for
other engines for the same model (Avalon was one GitHub search away). This denies `git clone`,
`hf download` / `huggingface-cli download`, `ollama pull`, `docker pull` and `curl|wget ... | sh`
installers whose target no scan in the last 14 days covers (alternatives_scan.py's registry). The
deny says how to clear it: run the alternatives-scan skill, or prefix the command with
ALT_SCAN_SKIP="<reason>" when it isn't an adoption (your own repo, a rebuild). Skips are logged.

Allowed without a scan: the Gitea host and localhost. FAIL OPEN on any error. ALT_GATE_OFF=1
turns it off. Every deny and skip appends to gate.jsonl in the scan state dir.
"""
import json
import os
import re
import shlex
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alternatives_scan as scan  # noqa: E402

OWN_HOSTS = {"10.0.0.100", "localhost", "127.0.0.1"}
PIPE_SH = re.compile(r"\b(?:curl|wget)\b[^|;&]*?(https?://\S+)[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b")
DOWNLOADS = {("git", "clone"), ("hf", "download"), ("huggingface-cli", "download"),
             ("ollama", "pull"), ("docker", "pull")}
# Options whose next word is their value, not the download target (referee 2026-11-03).
VALUE_OPTS = {"--depth", "-b", "--branch", "-o", "--origin", "--filter", "--reference", "-c",
              "--config", "-j", "--jobs", "--template", "--separate-git-dir", "--shallow-since",
              "--shallow-exclude", "-u", "--upload-pack", "--platform", "--repo-type", "--revision",
              "--local-dir", "--cache-dir", "--include", "--exclude", "--token", "-C",
              "--git-dir", "--work-tree"}
SHELLS = {"bash", "sh", "zsh", "dash"}


def host(target: str) -> str:
    """The host a target names: URL netloc, scp-style git@host:path, or '' for a bare name."""
    m = re.match(r"^[a-z][\w+.-]*://(?:[^@/]*@)?([^/:?#]+)", target, re.I)
    if m:
        return m.group(1).lower()
    m = re.match(r"^[\w.-]+@([\w.-]+):", target)
    return m.group(1).lower() if m else ""


def _segment_targets(words: list[str], depth: int) -> list[tuple[str, str | None]]:
    skip = None
    while words and re.fullmatch(r"[A-Za-z_]\w*=.*", words[0]):   # leading VAR=value
        name, _, value = words[0].partition("=")
        if name == "ALT_SCAN_SKIP" and value.strip():
            skip = value.strip()
        words = words[1:]
    while words and os.path.basename(words[0]) in ("sudo", "env", "command", "nice", "time"):
        words = words[1:]
    if not words:
        return []
    prog = os.path.basename(words[0])
    if prog in SHELLS and len(words) > 2 and words[1] == "-c" and depth < 2:
        return [(t, skip or s) for t, s in targets_with_skip(words[2], depth + 1)]
    rest = words[1:]
    if prog == "git":                      # git -C dir -c k=v clone ...
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree") else rest[1:]
    if not rest or (prog, rest[0]) not in DOWNLOADS:
        return []
    args, it = [], iter(rest[1:])
    for w in it:
        if w in VALUE_OPTS:
            next(it, None)
        elif not w.startswith("-"):
            args.append(w)
    return [(args[0], skip)] if args else []


HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.S)


def segments(command: str) -> list[list[str]]:
    """Simple commands as word lists. Heredoc bodies are data, not commands (2026-11-03: a memory
    note mentioning `git clone` in a heredoc was denied), and quotes are respected before any
    split on ; && || |, so `echo "a; git clone x"` is one echo."""
    command = HEREDOC.sub("\n", command)
    out = []
    for line in command.split("\n"):
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        try:
            tokens = list(lex)
        except ValueError:
            continue                       # unbalanced quotes: not a command we can read
        cur = []
        for tok in tokens:
            if tok and set(tok) <= set(";&|()"):
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append(tok)
        if cur:
            out.append(cur)
    return out


def targets_with_skip(command: str, depth: int = 0) -> list[tuple[str, str | None]]:
    out = [(m.group(1), None) for m in PIPE_SH.finditer(HEREDOC.sub("\n", command))]
    for words in segments(command):
        out += _segment_targets(words, depth)
    return [(t, s) for t, s in out if host(t) not in OWN_HOSTS]


def targets(command: str) -> list[str]:
    """Download targets in a shell command; an empty list means it isn't a gated download."""
    return [t for t, _ in targets_with_skip(command)]


def log(entry: dict) -> None:
    try:
        os.makedirs(scan.state_dir(), exist_ok=True)
        with open(os.path.join(scan.state_dir(), "gate.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": int(time.time()), **entry}) + "\n")
    except OSError:
        pass


def gate() -> int:
    if os.environ.get("ALT_GATE_OFF"):
        return 0
    event = json.load(sys.stdin)
    if not isinstance(event, dict) or event.get("tool_name") != "Bash":
        return 0
    ti = event.get("tool_input")
    command = str(ti.get("command") or "") if isinstance(ti, dict) else ""
    found = targets_with_skip(command)
    if not found:
        return 0
    skipped = [(t, s) for t, s in found if s]
    if skipped:
        log({"skip": skipped[0][1], "targets": [t for t, _ in skipped]})
    scans = scan.recent_scans()
    missing = [t for t, s in found if not s and not scan.covering_scan(t, scans)]
    if not missing:
        return 0
    log({"deny": missing})
    here = os.path.dirname(os.path.abspath(__file__))
    reason = (f"Big download with no alternatives scan in the last {scan.FRESH_DAYS} days: "
              + ", ".join(missing) + ". Run the alternatives-scan skill first (it finds what else "
              f"does this job and records the scan with `python3 {here}/alternatives_scan.py record`), "
              "then retry. If this isn't adopting something new (your own repo, a reinstall), "
              "prefix the command with ALT_SCAN_SKIP=\"<reason>\"; skips are logged.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


def main() -> int:
    try:
        return gate()
    except Exception:          # any surprise: allow, silently
        return 0


if __name__ == "__main__":
    sys.exit(main())
