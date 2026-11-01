#!/usr/bin/env python3
"""PreToolUse (Bash) hook: run a project's declared preflight checks before matching commands.

Why: a rule written in STANDARDS.md or a memory note is read only when the model remembers to
read it. mtw2 had "forced-events" on paper and still ran a turn-playing test into a papal
election (2026-11-01). A gate turns "before you run X, make sure Y" into a program that runs
every time, in every session, whatever the model remembers.

A project declares gates in <repo>/.claude/preflight.toml:

    [[gate]]
    id = "interrupting-events"   # the STANDARDS.md id it enforces
    match = '(?:^|[;&|(]\\s*)just\\s+qa(?![\\w-])'   # Python regex, searched in the command
    run = "python3 scripts/preflight_interrupts.py"   # exit 0 = go, anything else = deny
    why = "a test that plays turns must not meet a papal election"
    timeout = 60                 # seconds (default 60, capped at 100)

The check runs from the repo root with PREFLIGHT_COMMAND set to the command about to run.
A non-zero exit denies the call, and its output is the reason the model reads.

Trust: a gate runs shell, so a config counts only when its repo root is listed in
config/preflight-trusted.txt (one absolute path per line, # comments). Clones from the scout
or review/ never run their own preflight.toml.

Failure posture (settings entry: `bash <wrapper> || exit 1`, timeout 120; a deny is JSON on
exit 0):
  * no repo, no preflight.toml, an untrusted repo, or not a Bash call: allow, silently.
  * a preflight.toml that can't be parsed: deny every Bash call in that repo with the parse
    error. A broken gate that lets everything through is the failure this exists to stop, and
    the Edit tool still works to fix the file.
  * a check that times out or can't start: deny, saying so.
  * a crash inside this script: exit 1 (shown, never blocking).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

CONFIG = Path(".claude") / "preflight.toml"
DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 100  # the settings entry gives the hook 120 s; the check must finish inside it
MAX_REASON = 4000
STACK = Path(__file__).resolve().parent.parent
LOG = STACK / "state" / "hook-blocks.log"
TRUSTED = STACK / "config" / "preflight-trusted.txt"


def find_config(cwd: str) -> Path | None:
    """The nearest .claude/preflight.toml from cwd up to the git root (never above it)."""
    try:
        d = Path(cwd).resolve()
    except OSError:
        return None
    for p in (d, *d.parents):
        cand = p / CONFIG
        if cand.is_file():
            return cand
        if (p / ".git").exists():
            return None
    return None


def trusted_roots(path: Path = TRUSTED) -> set[Path]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    roots = set()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line:
            roots.add(Path(os.path.expanduser(line)).resolve())
    return roots


def load_gates(config: Path) -> list[dict]:
    """Parse and validate. Raises ValueError with a readable message on any problem."""
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot parse {config}: {exc}") from exc
    gates = data.get("gate", [])
    if not isinstance(gates, list):
        raise ValueError(f"{config}: `gate` must be an array of tables ([[gate]])")
    for i, g in enumerate(gates):
        if not isinstance(g, dict):
            raise ValueError(f"{config}: gate #{i + 1} must be a table")
        for key in ("id", "match", "run"):
            if not isinstance(g.get(key), str) or not g[key].strip():
                raise ValueError(f"{config}: gate #{i + 1} needs a non-empty string `{key}`")
        try:
            g["_re"] = re.compile(g["match"])
        except re.error as exc:
            raise ValueError(f"{config}: gate {g['id']!r} has a bad `match` regex: {exc}") from exc
        t = g.get("timeout", DEFAULT_TIMEOUT)
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
            raise ValueError(f"{config}: gate {g['id']!r} `timeout` must be a positive number")
        g["_timeout"] = min(float(t), MAX_TIMEOUT)
    return gates


def run_gate(gate: dict, root: Path, command: str) -> tuple[bool, str]:
    """(passed, output). A timeout or a check that can't start counts as failed."""
    env = {**os.environ, "PREFLIGHT_COMMAND": command, "PREFLIGHT_GATE": gate["id"]}
    timeout = gate["_timeout"]
    try:
        r = subprocess.run(gate["run"], shell=True, cwd=root, env=env, capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"the check did not finish within {timeout:g} s"
    except OSError as exc:
        return False, f"the check could not start: {exc}"
    out = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
    return r.returncode == 0, out or f"(exit {r.returncode}, no output)"


def deny(reason: str, session: str, what: str) -> None:
    try:
        if LOG.parent.is_dir():
            with LOG.open("a") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} BLOCKED preflight-gate {what} "
                         f"session={session}\n")
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason[:MAX_REASON],
    }}))


_CD = re.compile(r"(?:^|[;&|(]\s*)(?:cd|pushd)\s+(?:--\s+)?(['\"]?)([^\s;&|)'\"]+)\1")
_DASH_C = re.compile(r"(?:^|\s)-C\s+(['\"]?)([^\s;&|)'\"]+)\1")


def command_dirs(command: str, cwd: str) -> list[str]:
    """Where the command may run: the session cwd, plus each `cd X` / `pushd X` / `-C X` target,
    so `cd /other/repo && just qa` from another repo still meets that repo's gates."""
    dirs = [cwd]
    for rx in (_CD, _DASH_C):
        for m in rx.finditer(command):
            p = os.path.expanduser(m.group(2))
            dirs.append(p if os.path.isabs(p) else os.path.join(cwd, p))
    return dirs


def main(stdin=sys.stdin, trusted: set[Path] | None = None) -> int:
    try:
        data = json.load(stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    session = data.get("session_id") or "unknown"
    if not command:
        return 0
    trusted = trusted_roots() if trusted is None else trusted
    seen: set[Path] = set()
    for d in command_dirs(command, data.get("cwd") or os.getcwd()):
        config = find_config(d)
        if config is None or config in seen:
            continue
        seen.add(config)
        if config.parent.parent.resolve() in trusted and check_config(config, command, session):
            return 0
    return 0


def check_config(config: Path, command: str, session: str) -> bool:
    """Run one repo's gates against the command; True when it denied (the deny is printed)."""
    root = config.parent.parent.resolve()
    try:
        gates = load_gates(config)
    except ValueError as exc:
        deny(f"Preflight config is broken, so no gate in this repo can run:\n{exc}\n\n"
             f"Fix {config} with the Edit tool; every Bash call here is refused until it parses.",
             session, f"config-error={config}")
        return True
    for gate in gates:
        if not gate["_re"].search(command):
            continue
        ok, out = run_gate(gate, root, command)
        if ok:
            continue
        why = f"\nWhy this gate exists: {gate['why']}" if gate.get("why") else ""
        deny(f"Preflight gate '{gate['id']}' ({config}) refused this command.{why}\n\n"
             f"Check output:\n{out}\n\n"
             "Fix what the check reports, then run the command again. Don't reword the command "
             "to slip past the match: the gate is the project's own rule.",
             session, f"gate={gate['id']} root={root}")
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
