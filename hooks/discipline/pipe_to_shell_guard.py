#!/usr/bin/env python3
"""Pipe-to-shell guard: decide whether a Bash command runs downloaded code unseen.

Called by pipe-to-shell-guard.sh with the command on stdin. Exit 2 = block,
0 = allow. Any other outcome (crash, missing interpreter) makes the wrapper fall
back to a regex, so this never fails open.

Replaces the inline settings.json regex (2026-11-04), which had two defects:
  * `(bash|sh|zsh)` had no word boundary, so `curl … | sha256sum` was blocked;
  * `curl\\s.*\\|` ran across `;`, `&&` and quotes, so any later pipe into
    anything starting with "sh" counted.
This version tokenises the command (shlex, punctuation-aware), splits it into
commands (`;` `&&` `||` `&` newline) and pipeline stages (`|`), and judges words,
not substrings. Blocked:
  1. a curl/wget stage piped (directly or later in the same pipeline) into a shell;
  2. a shell fed by process substitution `<(curl …)` or by `$(curl …)` / backticks
     in its arguments (also `eval "$(curl …)"`);
  3. download-then-run in one command line: curl/wget writing a file
     (-o/-O/--output, or wget without -O-) and a later command executing THAT
     file (`bash i.sh`, `./i.sh`). Running some other script is not blocked.
A "shell" is bash/sh/zsh/dash/ksh/fish (any path), `$SHELL`/`${SHELL}`, or
`source`/`.` reading /dev/stdin. Wrappers (sudo, env, command, exec, nohup,
nice, time, timeout N) are skipped to find the real command word.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
SHELL_VARS = {"$SHELL", "${SHELL}"}
DOWNLOADERS = {"curl", "wget"}
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "nice", "time", "timeout", "doas"}
SEPARATORS = {";", "&&", "||", "&", "\n"}
SUBST_DL = re.compile(r"(\$\(|`)\s*(sudo\s+)?(curl|wget)\b")

# The old inline rule, with word boundaries: used only when tokenising fails
# (shlex can't parse nested quotes such as "$(python3 -c '…"…"…')"). A bare
# `$(curl …)` is an ordinary API call, so it counts only when a shell or eval runs it.
FALLBACK = re.compile(
    r"\b(curl|wget)\b[^\n;&|]*\|\s*(sudo\s+)?(\S*/)?(bash|sh|zsh|dash|ksh)\b"
    r"|\b(bash|sh|zsh)\s+<\(\s*(curl|wget)\b"
    r"|\b(bash|sh|zsh|dash|ksh|eval)\b[^\n;&|]*[\"'\s]\$\(\s*(curl|wget)\b"
)


HEREDOC = re.compile(r"(?<!<)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")


def strip_heredoc_bodies(cmd: str) -> str:
    """Drop heredoc bodies that are data (commit messages, notes, Python source).

    A body is kept only when the heredoc feeds a shell (`bash <<EOF`), because then
    its lines run as commands. Bodies that never close are kept (fail toward scanning).
    """
    lines = cmd.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = HEREDOC.search(line)
        i += 1
        if not m:
            continue
        before = re.split(r"[;&|(]", line[:m.start()])[-1].split()
        word = os.path.basename(before[0]) if before else ""
        while word in WRAPPERS and len(before) > 1:
            before = before[1:]
            word = os.path.basename(before[0])
        end = next((j for j in range(i, len(lines))
                    if (lines[j].lstrip("\t") if m.group(1) else lines[j]) == m.group(3)), None)
        if end is None or word in SHELLS:
            continue
        out.append(m.group(3))  # keep the delimiter line, drop the body
        i = end + 1
    return "\n".join(out)


def tokens(cmd: str) -> list[str]:
    cmd = strip_heredoc_bodies(cmd)
    # A newline after `|`, `&&`, `||` or a backslash continues the command (bash
    # reads `curl … |⏎ bash` as one pipeline); every other newline separates commands.
    cmd = re.sub(r"\\\n", " ", cmd)
    cmd = re.sub(r"(\|\||&&|\|)[ \t]*\n", r"\1 ", cmd)
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>()")
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def split_on(toks: list[str], seps: set[str]) -> list[list[str]]:
    out, cur = [], []
    for t in toks:
        if t in seps:
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    out.append(cur)
    return [c for c in out if c]


def command_word(stage: list[str]) -> tuple[str, list[str]]:
    """Return (basename of the real command, its arguments)."""
    i = 0
    while i < len(stage):
        w = stage[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):  # VAR=value prefix
            i += 1
            continue
        base = os.path.basename(w)
        if base in WRAPPERS:
            i += 1
            while i < len(stage) and (stage[i].startswith("-") or re.fullmatch(r"[0-9.]+[smhd]?", stage[i])):
                i += 1
            continue
        return base, stage[i + 1:]
    return "", []


def is_shell(word: str, args: list[str]) -> bool:
    if word in SHELLS or word in SHELL_VARS:
        return True
    if word in {"source", "."} and args and args[0] in {"/dev/stdin", "-"}:
        return True
    return False


def _url_names(args: list[str]) -> set[str]:
    return {os.path.basename(a.split("?", 1)[0].rstrip("/")) for a in args
            if re.match(r"(https?|ftp)://", a)} - {""}


def downloaded_files(word: str, args: list[str]) -> set[str]:
    """Basenames of the files this curl/wget invocation writes."""
    out: set[str] = set()
    if word == "curl":
        remote = False
        for i, a in enumerate(args):
            nxt = args[i + 1] if i + 1 < len(args) else ""
            if a in {"-o", "--output"} or re.fullmatch(r"-[A-Za-z]*o", a):
                if nxt and nxt != "-":
                    out.add(os.path.basename(nxt))
            elif a.startswith("--output="):
                out.add(os.path.basename(a.split("=", 1)[1]))
            elif a in {"-O", "--remote-name"} or re.fullmatch(r"-[A-Za-z]*O[A-Za-z]*", a):
                remote = True
        if remote:
            out |= _url_names(args)
    elif word == "wget":
        target = None
        for i, a in enumerate(args):
            nxt = args[i + 1] if i + 1 < len(args) else ""
            if a in {"-O", "--output-document"} or re.fullmatch(r"-[A-Za-z]*O", a):
                target = nxt
            elif a.startswith("--output-document="):
                target = a.split("=", 1)[1]
            elif re.fullmatch(r"-[A-Za-z]*O-", a):
                target = "-"
        if target is None:
            out |= _url_names(args)
        elif target != "-":
            out.add(os.path.basename(target))
    return out - {"", "-"}


def runs_one_of(word: str, stage: list[str], args: list[str], files: set[str]) -> bool:
    """Does this command execute one of the downloaded files?"""
    if not files:
        return False
    first = stage[0] if stage else ""
    if "/" in first and os.path.basename(first) in files:   # ./install.sh, /tmp/i.sh
        return True
    if is_shell(word, args):
        script = next((a for a in args if not a.startswith("-")), "")
        return bool(script) and os.path.basename(script) in files
    return False


def inner_scripts(stage: list[str]) -> list[str]:
    """Script strings handed to `<shell> -c` anywhere in a stage — directly, or via
    docker run / ssh / sudo / xargs. Each is a command line of its own."""
    found = []
    for k, t in enumerate(stage[:-2]):
        if os.path.basename(t) in SHELLS and re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", stage[k + 1]):
            found.append(stage[k + 2])
    return found


def verdict(cmd: str, depth: int = 0) -> str | None:
    """Return a reason string to block, or None to allow."""
    toks = tokens(cmd)
    commands = split_on(toks, SEPARATORS)
    files: set[str] = set()
    for command in commands:
        stages = split_on(command, {"|", "|&"})
        saw_download = False
        for stage in stages:
            word, args = command_word(stage)
            if depth < 3:
                for script in inner_scripts(stage):
                    reason = verdict(script, depth + 1)
                    if reason:
                        return f"{reason}, inside a -c script"
            if is_shell(word, args):
                if saw_download:
                    return "curl/wget output piped into a shell"
                if re.search(r"<\s*\(\s*(sudo\s+)?(curl|wget)\b", " ".join(stage)):
                    return "shell reading curl/wget via process substitution"
                if SUBST_DL.search(" ".join(args)):
                    return "shell running $(curl …) output"
            if word == "eval" and SUBST_DL.search(" ".join(args)):
                return "eval of $(curl …) output"
            if runs_one_of(word, stage, args, files):
                return "download and run in one command"
            if word in DOWNLOADERS:
                saw_download = True
                files |= downloaded_files(word, args)
    return None


def main() -> int:
    raw = sys.stdin.read()
    try:  # the PreToolUse payload; a bare command is accepted for tests and tools
        cmd = json.loads(raw).get("tool_input", {}).get("command") or ""
    except (ValueError, AttributeError):
        cmd = raw
    if not cmd.strip():
        return 0
    try:
        reason = verdict(cmd)
    except Exception:  # unparseable (unbalanced quotes …): judge by the regex
        reason = "pipe-to-shell pattern (fallback)" if FALLBACK.search(cmd) else None
    if reason:
        print(f"BLOCKED: Pipe-to-shell detected ({reason}). Download first, inspect, then execute.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
