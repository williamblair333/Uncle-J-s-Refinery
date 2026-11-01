#!/usr/bin/env python3
"""PreToolUse (Edit|Write|MultiEdit|NotebookEdit) hook: don't edit a repo another live session owns.

Why: 2026-11-01 the Uncle J session (and an agy job it launched) edited mtw2's bridge and runner
while a live mtw2 session was building the same feature in the same checkout: a branch switched
under it, its edits overwritten, its test file gone. Two writers in one working tree is a race
nobody sees until the other session reports it. The owner of a repo is the session working in it.

Rule: deny an edit when the target file's checkout (nearest .git file or dir above it, so a
worktree is its own checkout) is NOT this session's own checkout AND another live Claude session
has its working directory inside that checkout. Same-checkout edits are never touched.

Live sessions: each interactive Claude Code session keeps /run/user/<uid>/cc-socks/<pid>.sock;
a pid counts when it is alive, its argv[0] is `claude`, and it is not this hook's own ancestor.
Its folder is /proc/<pid>/cwd. That socket path is undocumented: `--selftest` prints what the
guard sees, so a CLI update that moves it shows up as "no sessions" instead of silence.

Override: a file `.claude/allow-cross-session-edits` in the target checkout (Bill's call).

Failure posture: settings entry `bash <wrapper> || exit 1`; a deny is JSON on exit 0; anything
else is exit 1 (shown, never blocking). Recovery: delete the PreToolUse entry naming
session-edit-guard from ~/.claude/settings.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

PATH_KEYS = ("file_path", "notebook_path", "path")
ALLOW_MARKER = Path(".claude") / "allow-cross-session-edits"
LOG = Path(__file__).resolve().parent.parent / "state" / "hook-blocks.log"


def checkout_root(path: str | Path) -> Path | None:
    """Nearest ancestor holding .git (dir for a clone, file for a worktree), or None."""
    try:
        p = Path(path).expanduser().resolve()
    except OSError:
        return None
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


def ancestors(pid: int, proc: Path) -> set[int]:
    out = set()
    while pid > 1 and pid not in out:
        out.add(pid)
        try:
            status = (proc / str(pid) / "status").read_text()
        except OSError:
            break
        ppid = next((ln.split()[1] for ln in status.splitlines() if ln.startswith("PPid:")), "0")
        pid = int(ppid)
    return out


def live_sessions(sock_dir: Path, proc: Path, me: int) -> list[tuple[int, Path]]:
    """(pid, cwd) of every live Claude session but this hook's own."""
    mine = ancestors(me, proc)
    found = []
    try:
        socks = sorted(sock_dir.glob("*.sock"))
    except OSError:
        return []
    for s in socks:
        if not s.stem.isdigit():
            continue
        pid = int(s.stem)
        if pid in mine:
            continue
        try:
            argv0 = (proc / str(pid) / "cmdline").read_bytes().split(b"\0", 1)[0].decode()
            cwd = Path(os.readlink(proc / str(pid) / "cwd"))
        except (OSError, UnicodeDecodeError):
            continue
        if os.path.basename(argv0) != "claude":
            continue
        found.append((pid, cwd))
    return found


def target_paths(tool_input: dict) -> list[str]:
    return [v for k in PATH_KEYS if isinstance(v := tool_input.get(k), str) and v]


def decide(data: dict, sock_dir: Path, proc: Path, me: int) -> str | None:
    """The deny reason, or None to allow."""
    cwd = data.get("cwd") or os.getcwd()
    own = checkout_root(cwd)
    sessions = None
    for target in target_paths(data.get("tool_input") or {}):
        full = target if os.path.isabs(target) else os.path.join(cwd, target)
        root = checkout_root(full)
        if root is None or root == own or (root / ALLOW_MARKER).exists():
            continue
        if sessions is None:
            sessions = live_sessions(sock_dir, proc, me)
        owners = [(pid, c) for pid, c in sessions if checkout_root(c) == root]
        if owners:
            who = ", ".join(f"pid {pid} in {c}" for pid, c in owners)
            return (f"Blocked by session-edit-guard: {full} is in {root}, which another live Claude "
                    f"session is working in ({who}). This session's checkout is {own or cwd}.\n\n"
                    "Two sessions editing one checkout overwrite each other (11-01: mtw2's young-Pope "
                    "work). Don't edit here. Send that session the change you want (ListAgents, then "
                    "SendMessage), or ask Bill. If Bill wants this session to edit there, he adds "
                    f"{root / ALLOW_MARKER}.")
    return None


def main(stdin=sys.stdin, sock_dir: Path | None = None, proc: Path = Path("/proc"),
         me: int | None = None) -> int:
    sock_dir = sock_dir or Path(f"/run/user/{os.getuid()}/cc-socks")
    me = os.getpid() if me is None else me
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        for pid, cwd in live_sessions(sock_dir, proc, me):
            print(pid, cwd, checkout_root(cwd))
        return 0
    try:
        data = json.load(stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    reason = decide(data, sock_dir, proc, me)
    if reason is None:
        return 0
    try:
        if LOG.parent.is_dir():
            with LOG.open("a") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} BLOCKED session-edit-guard "
                         f"tool={data.get('tool_name')} target={target_paths(data.get('tool_input') or {})} "
                         f"session={data.get('session_id', 'unknown')}\n")
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
