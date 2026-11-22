#!/usr/bin/env python3
"""PreToolUse (Bash) stall guard: refuse waits that can hang without anyone being told.

A background Bash command notifies its session only when it exits. Anything that can hang
without exiting, or exit with the wrong status, leaves the session idle until William asks.
On 2026-11-21 that cost write-well 2 h (two `ps | grep` waits matched each other), mtw2 3 h
(a `pgrep -f` matched its own `bash -c` line, in a loop with no clock) and hid a RAM stop
behind `| tail`. This merges write-well's comfy_guard.py and mtw2's preflight_waits.py.

Refused every time (exit 2, the reason on stderr):
1. self-match: a `pkill -f PAT`, or a `pgrep -f PAT` used as a test (loop or `if`
   condition, `&&`/`||`, `$(…)`, a count), or a `ps | grep PAT` wait, where PAT also matches
   elsewhere in the same command. The harness runs every command through `bash -c` (ssh
   does the same remotely), so the command is a process whose argv holds that text.
2. no-clock: a run_in_background `while/until … do … sleep … done` loop with no clock
   (SECONDS, date … +%, timeout, a counter): it ends only on success, so a hang is silent.
   (A foreground loop is already cut off by the Bash tool's own timeout.)
Advice, refused once per session per rule (the retry goes through), because the 30-day
replay (2026-11-22: 20,148 Bash calls, 875 in the background) had them on 49 and 62 calls
even once per session, and on 292 and 781 calls in all:
3. hidden-exit: a background command piped into another without `set -o pipefail`: the
   exit status the session is told is the last stage's (`tail`'s), not the job's.
4. no-deadline: a background command with no `timeout N`: if it hangs, no notification
   ever comes. `# no-deadline: <why>` marks a server meant to run until stopped.

Text the shell treats as data (quoted arguments, heredoc bodies, comments) is not read as
commands, except a quoted string or heredoc handed to `bash -c`/`sh -c`/`ssh`.
Reads the hook payload on stdin. Exit 0 = go, 2 = refused (reason on stderr).
Per-session advice state: ~/.claude/state/stall-guard/<session>.json.
Tests: tests/test_stall_guard.py. Bench: `just hook-bench --hook stall-guard`.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

MAX_SCAN = 50_000  # a longer command is data (a pasted file); judging it isn't worth the time
ADVICE = ("hidden-exit", "no-deadline")
STATE = Path(os.environ.get("STALL_GUARD_STATE") or Path.home() / ".claude" / "state" / "stall-guard")
# a quoted string or heredoc that the shell runs as code
_CODE_OPENER = re.compile(r"(?:\bssh\b[^;&|\n]*|\b(?:ba|z|da)?sh\s+(?:-\w+\s+)*-c\s*|\beval\s+)$")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_SHELL_WORD = re.compile(r"(?:^|[\s;&|(])(?:(?:ba|z|da)?sh|ssh)(?=\s|$)")
PGREP_AT = re.compile(r"(?<![\w./-])p(grep|kill)\b")
PS_AT = re.compile(r"(?<![\w./-])ps\b")
LOOP_KW = re.compile(r"\b(?:until|while)\b")
DO_KW = re.compile(r"(?:;|\n)\s*do\b")
DONE_KW = re.compile(r"\bdone\b")


class Loop:
    """One `while/until COND; do BODY; done`, found by a forward scan (linear, unlike a
    backtracking regex over a 20 KB heredoc). Nested loops end at the first `done`."""

    def __init__(self, start: int, cond: tuple[int, int], body: tuple[int, int], end: int, code: str):
        self.start, self.end = start, end
        self.cond_start = cond[0]
        self.cond, self.body = code[cond[0]:cond[1]], code[body[0]:body[1]]


def loops(code: str):
    pos = 0
    while True:
        k = LOOP_KW.search(code, pos)
        if not k:
            return
        d = DO_KW.search(code, k.end())
        if not d:
            return
        e = DONE_KW.search(code, d.end())
        if not e:
            return
        between = DONE_KW.search(code, k.end(), d.start())
        if between is None:  # a `done` before this `do` means `while` was a word, not a loop
            yield Loop(k.start(), (k.end(), d.start()), (d.end(), e.start()), e.end(), code)
        pos = k.end()
CLOCK = re.compile(r"\bSECONDS\b|\bdate\b[^;&|\n)]*\+%|\btimeout\b|\$\(\(\s*\w+\s*[+-]|\(\(\s*\w+\s*(?:\+\+|\+=)"
                   r"|\b\w+\+\+")
TIMEOUT = re.compile(r"\btimeout\b(?:\s+-{1,2}[\w-]+(?:=\S+|\s(?![\d$\"])\S+)?)*\s+(?:\d|\$|\"\$)")
NO_DEADLINE = re.compile(r"#\s*no-deadline:\s*\S")
PGREP_VALUE_FLAGS = set("PuUGgtsFn") | {"--parent", "--euid", "--uid", "--group", "--pgroup",
                                        "--terminal", "--session", "--pidfile", "--ns", "--signal"}
GREP_VALUE_FLAGS = set("mABCef") | {"--max-count", "--regexp", "--file"}


def code_view(cmd: str) -> str:
    """The command with data blanked to spaces (same length, so offsets line up): quoted
    strings, comments, heredoc bodies. Quoted strings and heredocs run by `bash -c` / `ssh`
    are code, so they stay. Pipes and words inside data then can't look like commands."""
    out = list(cmd)
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"":
            j = i + 1
            while j < n and cmd[j] != c:
                j += 2 if (c == '"' and cmd[j] == "\\") else 1
            if not _CODE_OPENER.search(cmd[max(0, i - 200):i]):
                for k in range(i + 1, min(j, n)):
                    if out[k] != "\n":
                        out[k] = " "
            i = j + 1
            continue
        if c == "#" and (i == 0 or cmd[i - 1] in " \t\n;&|("):
            j = cmd.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            m = _HEREDOC.match(cmd, i)
            if m:
                line_start = cmd.rfind("\n", 0, i) + 1
                # a shell reads it (`bash <<EOF`, `ssh host <<EOF`), not `cat > x.sh <<EOF`
                runs_code = _SHELL_WORD.search(cmd[line_start:i])
                body = cmd.find("\n", m.end())
                end = re.compile(rf"^\t*{re.escape(m.group(2))}$", re.M).search(cmd, body + 1) if body >= 0 else None
                stop = end.start() if end else n
                if body >= 0 and not runs_code:
                    for k in range(body + 1, stop):
                        if out[k] != "\n":
                            out[k] = " "
                i = (end.end() if end else n)
                continue
        i += 1
    return "".join(out)


def _segment(code: str, start: int) -> str:
    """From start to the end of that simple command (unquoted ; & | newline or `)`)."""
    m = re.compile(r"[;&|\n)`]").search(code, start)
    return code[start:m.start() if m else len(code)]


def _args_pattern(seg: str, value_flags: set[str]) -> tuple[list[str], str | None]:
    """Short/long flags and the first operand (the pattern) of a pgrep/grep word list."""
    try:
        words = shlex.split(seg)[1:]
    except ValueError:
        words = seg.split()[1:]
    flags, i = [], 0
    while i < len(words):
        w = words[i]
        if w == "--":
            return flags, words[i + 1] if i + 1 < len(words) else None
        if w.startswith("--"):
            flags.append(w)
            if "=" not in w and w in value_flags:
                i += 1
        elif w.startswith("-") and len(w) > 1:
            flags.append(w)
            if w[-1] in value_flags:  # -P 1, -m 1: the value is the next word
                i += 1
        else:
            return flags, w
        i += 1
    return flags, None


def _matches_elsewhere(pattern: str, cmd: str, start: int, end: int) -> bool:
    try:
        rx = re.compile(pattern)
    except re.error:
        return False
    rest = cmd[:start] + cmd[end:]
    return bool(rx.search(rest))


def _pattern_span(cmd: str, seg_start: int, seg_len: int, pattern: str) -> tuple[int, int]:
    """Where the pattern's text sits in the raw command (quotes included), to cut it out."""
    seg = cmd[seg_start:seg_start + seg_len]
    for quoted in (f"'{pattern}'", f'"{pattern}"', pattern):
        k = seg.rfind(quoted)
        if k >= 0:
            return seg_start + k, seg_start + k + len(quoted)
    return seg_start, seg_start + seg_len


def _is_test(code: str, start: int, end: int, flags: list[str]) -> bool:
    """A pgrep whose answer decides something: a loop/if condition, &&/||, $(…), a count."""
    before = code[max(0, start - 40):start]
    after = code[end:end + 60]
    if re.search(r"(?:\b(?:while|until|if|elif)|!|\$\(|`)\s*$", before):
        return True
    if re.match(r"\s*(?:[0-9]?>\s*/dev/null\s*|2>&1\s*)*(?:&&|\|\|)", after):
        return True
    return any(f.startswith("-") and not f.startswith("--") and "c" in f for f in flags) \
        or "--count" in flags


def self_matches(cmd: str, code: str) -> list[str]:
    out = []
    for m in PGREP_AT.finditer(code):
        seg = _segment(code, m.start())
        flags, pattern = _args_pattern(cmd[m.start():m.start() + len(seg)], PGREP_VALUE_FLAGS)
        has_f = any((f.startswith("-") and not f.startswith("--") and "f" in f) or f == "--full"
                    for f in flags)
        if not pattern or not has_f or any("x" in f for f in flags if not f.startswith("--")):
            continue  # -x: the whole command line must match the pattern
        if m.group(1) == "grep" and not _is_test(code, m.start(), m.start() + len(seg), flags):
            continue  # a pgrep whose output is only read: a self-line is noise, not a hang
        if "$$" in cmd:
            continue  # `[ "$p" != "$$" ]`: it skips its own shell
        s, e = _pattern_span(cmd, m.start(), len(seg), pattern)
        if _matches_elsewhere(pattern, cmd, s, e):
            out.append(f"self-match: p{m.group(1)} -f {pattern} matches text elsewhere in this same "
                       "command, which is itself a running process (bash -c / ssh), so it finds "
                       "itself. Use a PID, pgrep -x, or a pattern found nowhere else in the command.")
    for loop in loops(code):
        for m in PS_AT.finditer(loop.cond):
            at = loop.cond_start + m.start()
            stages = re.split(r"(?<!\|)\|(?!\|)", _pipeline(cmd, at))
            if any(re.search(r"\bgrep\b.*-\w*v\w*\s+['\"]?grep\b", st) for st in stages):
                continue
            for st in stages[1:]:
                st_start = cmd.find(st, at)
                if not re.match(r"\s*grep\b", st):
                    continue
                flags, pattern = _args_pattern(cmd[st_start:st_start + len(st)].strip(), GREP_VALUE_FLAGS)
                if not pattern or any("v" in f for f in flags if not f.startswith("--")):
                    continue
                s, e = _pattern_span(cmd, st_start, len(st), pattern)
                if _matches_elsewhere(pattern, cmd, s, e):
                    out.append(f"self-match: `ps | grep {pattern}` in a wait loop matches this same "
                               "command line, so the wait never ends (two such waits wait on each "
                               "other). Wait on a PID (`wait $pid`, `tail --pid`) or a lock instead.")
    return out


def _pipeline(code: str, start: int) -> str:
    m = re.compile(r"[;&\n)]|\|\|").search(code, start)
    return code[start:m.start() if m else len(code)]


def problems(cmd: str, background: bool = False) -> list[str]:
    if len(cmd) > MAX_SCAN:
        return []
    code = code_view(cmd)
    out = self_matches(cmd, code)
    if background:
        for loop in loops(code):
            if re.match(r"\s*read\b", loop.cond):
                continue  # `while read`: ends with its input
            raw = cmd[loop.start:loop.end]  # code_view keeps offsets; $(date …) sits in quotes
            bounded = CLOCK.search(raw) or TIMEOUT.search(cmd[:loop.start])
            if re.search(r"\bsleep\b", loop.body) and not bounded:
                out.append("no-clock: a background wait loop with no deadline or stall check ends "
                           "only on success, so a hang is silent. Track time (SECONDS / date +%s / "
                           "timeout N) and break with a STALLED or DEADLINE line.")
                break
        if re.search(r"(?<!\|)\|(?![|&])", code) and "pipefail" not in code:
            out.append("hidden-exit: a background command piped into another reports the last "
                       "stage's exit code, so a failure reads as success. Add `set -o pipefail;` "
                       "or write to a log (`> log 2>&1`) and read it after.")
        if not TIMEOUT.search(cmd) and not NO_DEADLINE.search(cmd):
            out.append("no-deadline: a background command with no `timeout N` never notifies if it "
                       "hangs. Prefix `timeout <secs>` (longer than it should ever take), or add "
                       "`# no-deadline: <why>` for a server meant to run until stopped.")
    return out


def _rule(problem: str) -> str:
    return problem.split(":", 1)[0]


def _warned(session: str) -> set[str]:
    try:
        return set(json.loads((STATE / f"{session}.json").read_text()).get("warned", []))
    except (OSError, ValueError, AttributeError):
        return set()


def _mark(session: str, rules: set[str]) -> bool:
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        tmp = STATE / f".{session}.{os.getpid()}"
        tmp.write_text(json.dumps({"warned": sorted(rules)}))
        os.replace(tmp, STATE / f"{session}.json")
        return True
    except OSError:
        return False


def decide(data: dict) -> list[str]:
    """The reasons to refuse this call (empty = let it run). Records the advice it gives."""
    if data.get("tool_name", "Bash") != "Bash":
        return []
    inp = data.get("tool_input") or {}
    found = problems(str(inp.get("command") or ""), inp.get("run_in_background") is True)
    hard = [p for p in found if _rule(p) not in ADVICE]
    if hard:
        return hard  # fix these first; advice waits for a call that would otherwise run
    advice = [p for p in found if _rule(p) in ADVICE]
    session = re.sub(r"[^\w-]", "", str(data.get("session_id") or ""))[:80] or "no-session"
    warned = _warned(session)
    new = [p for p in advice if _rule(p) not in warned]
    # Mark before refusing: if the mark can't be written, the advice could repeat forever.
    if new and _mark(session, warned | {_rule(p) for p in new}):
        return [p + " (advice: shown once per session; retry to run it as is)" for p in new]
    return []


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(data, dict):
        return 0
    found = decide(data)
    if not found:
        return 0
    print("stall-guard: " + " | ".join(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
