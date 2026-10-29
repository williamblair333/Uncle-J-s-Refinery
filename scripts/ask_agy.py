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
  response is empty; `denied` names the command (agy's own entry says only "RunCommand");
- the response is empty or the status is not SUCCESS.

Shell access is governed by features/antigravity/permissions.json (read-only allow list),
applied with features/antigravity/apply_permissions.py. `--edits` adds
`--mode accept-edits` so the agent may write files inside --cwd.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
# python3, find, sed, jq... run through sandbox-run when agy reaches for them (see _shim)
SHIMS = _REPO / "features" / "antigravity" / "shims"

# A failed lookup agy then worked around (a guessed path, a wrong MCP argument) does not fail
# the job; a failed command, edit or write does, since the response may claim it worked.
READ_TOOLS = {"read_file", "view_file", "list_dir", "grep_search", "find_by_name", "call_mcp_tool"}
_DENY_ERROR = re.compile(r"permission denied|deny rule|permission check failed", re.I)


def fatal_tool_error(err: dict) -> bool:
    return err.get("tool") not in READ_TOOLS or bool(_DENY_ERROR.search(err.get("message") or ""))


def agy_env() -> dict:
    """agy's environment: the shims first on PATH, so habitual commands run sandboxed."""
    env = dict(os.environ)
    env["PATH"] = f"{SHIMS}{os.pathsep}{env.get('PATH', '')}"
    return env


def describe_denied(action: dict, step: dict = None) -> str:
    """'RunCommand: touch x' from a denied_actions entry and the tool step it denied."""
    name = action.get("display_name") or action.get("action")
    if not step:
        return name
    params = (step.get("tool_info") or {}).get("parameters") or {}
    what = params.get("CommandLine") or (
        json.dumps(params, separators=(",", ":")) if params else step.get("tool_name"))
    return f"{name}: {what}" if what else name


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

    tool_errors, tool_steps, final = [], {}, None
    tool_by_index = {}
    conversation_id = None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "init":
            init_payload = event.get("init")
            cid = event.get("conversation_id")
            if not cid and isinstance(init_payload, dict):
                cid = init_payload.get("conversation_id")
            if cid:
                conversation_id = str(cid)
        step = event.get("step_update") or {}
        if step.get("step_type") == "tool":
            s_idx = step.get("step_index")
            tool_steps[s_idx] = step
            t_name = step.get("tool_name") or ""
            if t_name == "call_mcp_tool":
                params = (step.get("tool_info") or {}).get("parameters") or {}
                server = next((v for k, v in params.items() if k.lower() in ("servername", "server", "server_name")), None)
                if not server:
                    info = step.get("tool_info") or {}
                    if isinstance(info, dict):
                        server = next((v for k, v in info.items() if k.lower() in ("servername", "server", "server_name")), None)
                key = f"mcp:{server}" if server else "mcp"
            else:
                key = t_name
            if key:
                tool_by_index[s_idx] = key
        if step.get("step_type") == "tool" and step.get("state") == "ERROR":
            info = step.get("tool_info") or {}
            tool_errors.append({
                "tool": step.get("tool_name"),
                "input": (info.get("parameters") or {}).get("CommandLine"),
                "message": (info.get("error") or {}).get("message", ""),
            })
        if event.get("event") == "result":
            final = event.get("result") or {}

    tool_counts = {}
    for k in tool_by_index.values():
        tool_counts[k] = tool_counts.get(k, 0) + 1

    out = {"ok": False, "response": "", "tool_errors": tool_errors, "denied": [], "tools": tool_counts}
    if conversation_id:
        out["conversation_id"] = conversation_id
    stderr_tail = (proc.stderr or "").strip()[-600:]
    timed_out = "print timeout" in (proc.stderr or "")
    if final is None:
        out["error"] = (f"agy hit its print timeout ({timeout}s); the response is partial"
                        if timed_out else
                        f"no result event (agy exit {proc.returncode}): {proc.stderr.strip()[-400:]}")
        if stderr_tail:
            out["detail"] = stderr_tail
        return out
    out["response"] = (final.get("response") or "").strip()
    # an auto-deny ends the turn, so the denied actions are the last tool steps
    denied, steps = final.get("denied_actions") or [], list(tool_steps.values())
    recent = ([None] * len(denied) + steps)[len(steps):]
    out["denied"] = [describe_denied(a, s) for a, s in zip(denied, recent)]
    out["usage"] = final.get("usage")
    if timed_out:
        out["error"] = f"agy hit its print timeout ({timeout}s); the response is partial"
        if stderr_tail:
            out["detail"] = stderr_tail
    elif final.get("status") != "SUCCESS":
        out["error"] = f"status {final.get('status')}"
        err = final.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or json.dumps(err)
        elif err:
            detail = str(err).strip()
        else:
            detail = ""
        if not detail:
            detail = stderr_tail
        if not detail and tool_errors:
            detail = tool_errors[-1].get("message") or ""
        if detail:
            out["detail"] = detail
    elif any(fatal_tool_error(e) for e in tool_errors) or (tool_errors and not out["response"]):
        out["error"] = "a tool call failed (deny rule or tool error); the response may claim otherwise"
        if stderr_tail:
            out["detail"] = stderr_tail
    elif out["denied"]:
        out["error"] = "headless mode auto-denied an action not on the allow list"
        if stderr_tail:
            out["detail"] = stderr_tail
    elif not out["response"]:
        out["error"] = "empty response"
        if stderr_tail:
            out["detail"] = stderr_tail
    else:
        out["ok"] = True
        if tool_errors:
            out["warning"] = f"{len(tool_errors)} lookup(s) failed and agy worked around them"
    return out


def _log(args, out: dict, elapsed: float) -> None:
    log_env = os.environ.get("DELEGATE_LOG")
    if log_env == "":
        return
    log_path = Path(log_env) if log_env else _REPO / "state" / "delegate.jsonl"
    project = os.path.basename(os.path.normpath(args.cwd))
    rec = {"ts": round(time.time(), 1), "backend": "agy", "model": args.model or "agy-default",
           "project": project, "via": "cli",
           "seconds": round(elapsed, 1), "ok": bool(out["ok"])}
    if not out.get("ok"):
        rec["error"] = str(out.get("error", ""))[:200]
    if out.get("tools"):
        rec["tools"] = out["tools"]
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


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
    started = time.time()
    out = ask(prompt, agy_bin=args.agy_bin, cwd=args.cwd, edits=args.edits,
              timeout=args.timeout, model=args.model)
    _log(args, out, time.time() - started)
    if out["ok"]:
        print(out["response"])
        return 0
    print(json.dumps(out, indent=2), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
