#!/usr/bin/env python3
"""PreToolUse(Bash) doc gate: block a `git commit` in THIS repo until the docs
.session-end.yml declares mandatory are staged.

Reads the hook payload on stdin. Prints a PreToolUse "deny" decision to
block; prints nothing to allow. Always exits 0 and fails open: a broken guard
must never wedge a commit (git's own pre-commit hook, session-end-check.sh, is
the second gate).

Why this is a parser and not a regex. The inline hook it replaces matched
`\\bgit\\b.*\\bcommit\\b` against the whole command string, so it fired on
read-only calls that merely mention both words (`git rev-parse HEAD^{commit}`,
`git ls-remote ... # commit`, a `gh api .../commit/...` next to a git call), and
it always inspected the staged files of the hardcoded stack checkout — so a
commit inside a nested, gitignored, independent clone (review/rea) was judged by
the stack repo's index. Now only a real `git ... commit` invocation counts, and
only when its target repository shares this repo's git common dir (so linked
worktrees of this repo are gated; nested clones and other repos are not).

Policy (mandatory list, trigger.file_types) comes from the target's
.session-end.yml — the same file session-end-check.sh reads — so the two gates
cannot drift apart again.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field

SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;", "\n"}
# git global options that take a separate argument.
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                     "--super-prefix", "--config-env", "--exec-path"}
# commit options whose value is a separate token (or glued, for short ones).
COMMIT_OPTS_WITH_ARG = {"-m", "--message", "-F", "--file", "-C", "--reuse-message",
                        "-c", "--reedit-message", "-t", "--template", "--author",
                        "--date", "--cleanup", "--fixup", "--squash",
                        "--trailer", "--pathspec-from-file"}
SHORT_WITH_ARG = set("mFCct")
STAGING_SUBCOMMANDS = {"add", "rm", "mv", "stage"}
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


@dataclass
class GitCall:
    subcommand: str
    cwd: str
    args: list[str] = field(default_factory=list)


def strip_heredocs(command: str) -> str:
    """Drop heredoc bodies so text inside them is never parsed as commands."""
    out: list[str] = []
    terminators: list[str] = []
    for line in command.split("\n"):
        if terminators:
            if line.strip() == terminators[0]:
                terminators.pop(0)
            continue
        out.append(line)
        terminators.extend(m.group(2) for m in HEREDOC_RE.finditer(line))
    return "\n".join(out)


def _tokens(command: str) -> list[str]:
    lex = shlex.shlex(strip_heredocs(command).replace("\n", " ; "),
                      posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    lex.commenters = "#"
    return list(lex)


def _segments(tokens: list[str]) -> list[list[str]]:
    segs: list[list[str]] = [[]]
    for t in tokens:
        if t in SEPARATORS:
            segs.append([])
        else:
            segs[-1].append(t)
    return [s for s in segs if s]


def _resolve(base: str, path: str) -> str:
    return os.path.normpath(os.path.join(base, os.path.expanduser(path)))


def parse_git_calls(command: str, cwd: str) -> list[GitCall]:
    """Every `git <subcommand>` invocation in a shell command, in order, with the
    directory it targets (`cd X &&` and `git -C X` both honoured)."""
    calls: list[GitCall] = []
    here = cwd
    for seg in _segments(_tokens(command)):
        i = 0
        while i < len(seg) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]):
            i += 1  # VAR=value prefixes
        while i < len(seg) and seg[i] in {"command", "exec", "time", "nohup"}:
            i += 1
        if i >= len(seg):
            continue
        if seg[i] == "cd":
            here = _resolve(here, seg[i + 1]) if i + 1 < len(seg) else os.path.expanduser("~")
            continue
        if os.path.basename(seg[i]) != "git":
            continue
        i += 1
        target = here
        while i < len(seg) and seg[i].startswith("-"):
            opt = seg[i]
            if opt in GIT_OPTS_WITH_ARG:
                if opt == "-C" and i + 1 < len(seg):
                    target = _resolve(target, seg[i + 1])
                i += 2
            else:
                i += 1
        if i < len(seg):
            calls.append(GitCall(seg[i], target, seg[i + 1:]))
    return calls


def commit_flags(args: list[str]) -> tuple[bool, list[str]]:
    """(stages_everything, messages) for the arguments after `git commit`."""
    all_flag = False
    messages: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a in ("-a", "--all"):
            all_flag = True
        elif a in ("-m", "--message"):
            if i + 1 < len(args):
                messages.append(args[i + 1])
            i += 1
        elif a.startswith("--message="):
            messages.append(a.split("=", 1)[1])
        elif a.startswith("--"):
            if a in COMMIT_OPTS_WITH_ARG:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            cluster = a[1:]
            for j, ch in enumerate(cluster):
                if ch == "a":
                    all_flag = True
                elif ch in SHORT_WITH_ARG:
                    value = cluster[j + 1:]
                    if not value and i + 1 < len(args):
                        value = args[i + 1]
                        i += 1
                    if ch == "m":
                        messages.append(value)
                    break
        i += 1
    return all_flag, messages


def skips_hooks(args: list[str]) -> bool:
    """True for `--no-verify` or a short cluster carrying `n` before any arg-taking flag."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return False
        if a == "--no-verify":
            return True
        if a.startswith("--"):
            if a in COMMIT_OPTS_WITH_ARG:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for ch in a[1:]:
                if ch == "n":
                    return True
                if ch in SHORT_WITH_ARG:
                    if a.endswith(ch):
                        i += 1  # value is the next arg
                    break
        i += 1
    return False


def _git(cwd: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                           text=True, encoding="utf-8", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def common_dir(path: str) -> str | None:
    if not os.path.isdir(path):
        return None
    out = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.realpath(out) if out else None


def _load_policy(toplevel: str) -> tuple[list[str], list[str]] | None:
    try:
        import yaml  # noqa: PLC0415 — only needed once a commit is in scope
        with open(os.path.join(toplevel, ".session-end.yml"), encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception:
        return None
    types = (cfg.get("trigger") or {}).get("file_types") or []
    return list(cfg.get("mandatory") or []), list(types)


def missing_docs(toplevel: str) -> list[str]:
    policy = _load_policy(toplevel)
    if policy is None:
        return []
    mandatory, types = policy
    staged_out = _git(toplevel, "diff", "--cached", "--name-only")
    staged = [s for s in (staged_out or "").splitlines() if s.strip()]
    if not staged:
        return []
    if types and not any(f.endswith(tuple(types)) for f in staged):
        return []
    return [f for f in mandatory if f not in staged]


def decide(command: str, cwd: str, repo_root: str) -> str | None:
    """Return a block reason, or None to allow."""
    calls = parse_git_calls(command, cwd)
    if not any(c.subcommand == "commit" for c in calls):
        return None
    ours = common_dir(repo_root)
    if ours is None:
        return None
    staged_earlier = False
    for call in calls:
        if call.subcommand in STAGING_SUBCOMMANDS:
            staged_earlier = True
            continue
        if call.subcommand != "commit":
            continue
        if common_dir(call.cwd) != ours:
            continue  # another repo, or a nested independent clone
        all_flag, messages = commit_flags(call.args)
        if any(m.startswith("chk:") for m in messages):
            continue  # checkpoint commits are exempt
        if skips_hooks(call.args):
            return ("Commit blocked - --no-verify/-n skips the doc gate. Stage the missing "
                    "docs instead (CHANGELOG.md, HANDOFF.md, ...), or use a chk: message.")
        if all_flag or staged_earlier:
            # The index is not final yet at PreToolUse time; git's own pre-commit
            # hook (session-end-check.sh) judges the real staged set.
            continue
        toplevel = _git(call.cwd, "rev-parse", "--show-toplevel")
        if not toplevel:
            continue
        missing = missing_docs(toplevel)
        if missing:
            return "Commit blocked - update first: " + " ".join(missing)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        command = (payload.get("tool_input") or {}).get("command") or ""
        cwd = payload.get("cwd") or os.getcwd()
    except Exception:
        return 0
    repo_root = os.environ.get("COMMIT_DOC_GUARD_ROOT") or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    try:
        reason = decide(command, cwd, repo_root)
    except Exception:
        return 0  # fail open
    if reason:
        # Deny this one tool call. {"continue": false} would end the whole turn, which is
        # how four subagents stopped mid-task on 2026-10-22 instead of fixing their docs.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
