#!/usr/bin/env python3
"""Run one Antigravity CLI (agy) prompt headless and report honestly whether it worked.

Usage:
  ask_agy.py [--cwd DIR] [--edits] [--timeout SECONDS] [--model M] PROMPT
  ask_agy.py --prompt-file FILE ...

Prints the response on stdout and exits 0 only when the turn really succeeded. Exits 1
with a JSON summary on stderr when it did not. agy itself reports status SUCCESS and
exit 0 in all of these cases, which is why this wrapper exists:

- a command matched a deny rule: a tool step ends in ERROR, the model often still
  answers "DONE", and `denied_actions` in the result is empty;
- a command was on no list: print mode soft-denies it (`denied_actions` is set) and the
  response is empty;
- the response is empty or the status is not SUCCESS.

Shell access is governed by features/antigravity/permissions.json (read-only allow list),
applied with features/antigravity/apply_permissions.py. `--edits` adds
`--mode accept-edits` so the agent may write files inside --cwd.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# python3, find, sed, jq... run through sandbox-run when agy reaches for them (see _shim)
SHIMS = Path(__file__).resolve().parent.parent / "features" / "antigravity" / "shims"


def agy_env() -> dict:
    """agy's environment: the shims first on PATH, so habitual commands run sandboxed."""
    env = dict(os.environ)
    env["PATH"] = f"{SHIMS}{os.pathsep}{env.get('PATH', '')}"
    return env


def ask(prompt: str, agy_bin: str = None, cwd: str = None, edits: bool = False,
        timeout: int = 300, model: str = None) -> dict:
    agy = agy_bin or os.environ.get("AGY_BIN") or "agy"
    cmd = [agy, "-p", prompt, "--output-format", "stream-json", "--print-timeout", f"{timeout}s"]
    if edits:
        cmd += ["--mode", "accept-edits"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout + 60,
                              env=agy_env())
    except FileNotFoundError:
        return {"ok": False, "error": f"agy not found: {agy}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"agy did not finish within {timeout + 60}s"}

    tool_errors, final = [], None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        step = event.get("step_update") or {}
        if step.get("step_type") == "tool" and step.get("state") == "ERROR":
            info = step.get("tool_info") or {}
            tool_errors.append({
                "tool": step.get("tool_name"),
                "input": (info.get("parameters") or {}).get("CommandLine"),
                "message": (info.get("error") or {}).get("message", ""),
            })
        if event.get("event") == "result":
            final = event.get("result") or {}

    out = {"ok": False, "response": "", "tool_errors": tool_errors, "denied": []}
    if final is None:
        out["error"] = f"no result event (agy exit {proc.returncode}): {proc.stderr.strip()[-400:]}"
        return out
    out["response"] = (final.get("response") or "").strip()
    out["denied"] = [a.get("display_name") or a.get("action") for a in final.get("denied_actions") or []]
    out["usage"] = final.get("usage")
    if final.get("status") != "SUCCESS":
        out["error"] = f"status {final.get('status')}"
    elif tool_errors:
        out["error"] = "a tool call failed (deny rule or tool error); the response may claim otherwise"
    elif out["denied"]:
        out["error"] = "headless mode auto-denied an action not on the allow list"
    elif not out["response"]:
        out["error"] = "empty response"
    else:
        out["ok"] = True
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--prompt-file")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--edits", action="store_true", help="allow file edits inside --cwd")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--model")
    ap.add_argument("--agy-bin")
    args = ap.parse_args(argv)
    prompt = open(args.prompt_file, encoding="utf-8").read() if args.prompt_file else args.prompt
    if not prompt:
        ap.error("a prompt or --prompt-file is required")
    out = ask(prompt, agy_bin=args.agy_bin, cwd=args.cwd, edits=args.edits,
              timeout=args.timeout, model=args.model)
    if out["ok"]:
        print(out["response"])
        return 0
    print(json.dumps(out, indent=2), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
