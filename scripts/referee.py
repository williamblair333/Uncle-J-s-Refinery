#!/usr/bin/env python3
"""Cross-provider referee: Gemini (through agy) judges work that Claude produced.

Usage:
  referee.py --task "what the work was meant to do" --diff [REV]   [--cwd DIR]
  referee.py --task-file TASK.md --file a.py --file b.py
  referee.py --task "..." --work-file notes.md

The work goes to Google through the Antigravity CLI on the AI Pro subscription, read-only
(agy may run the read-only commands in features/antigravity/permissions.json inside --cwd
to check claims). Credential-like paths and content that looks like a secret are refused
before agy runs, and work over MAX_WORK_CHARS is refused rather than truncated.

Prints the verdict as JSON on stdout. Exit codes:
  0 pass   2 fail   3 unsure   1 error (agy failed, reply unparseable, input refused)

A reply that is not a well-formed verdict is an error, never a pass. A "pass" that carries a
high-severity finding is downgraded to "unsure". Each run appends one line to
state/referee.jsonl (verdict and counts, never the task or the work) so its value can be
measured; REFEREE_LOG overrides the path and an empty value disables it.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ask_agy", Path(__file__).resolve().parent / "ask_agy.py")
ask_agy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ask_agy)

MAX_WORK_CHARS = 60_000
# Pinned because agy also serves Claude models, and a Claude referee defeats the purpose.
# Flash (medium) answered a 10 KB file review in ~3.5 min; agy's default model ran past 4.
DEFAULT_MODEL = "gemini-3.8-flash-medium"
DEFAULT_TIMEOUT = 600
VERDICTS = ("pass", "fail", "unsure")
SEVERITIES = ("high", "medium", "low")
EXIT = {"pass": 0, "fail": 2, "unsure": 3}

_CRED_PATH = re.compile(r"(^|/)(\.env(\..*)?|\.netrc|\.pgpass|id_[a-z0-9]+|.*\.(pem|key|p12|pfx)"
                        r"|(credentials?|secrets?)(\.[a-z]+)?)$"
                        r"|(^|/)(\.ssh|\.aws|\.gnupg|credentials?|secrets?)/", re.I)
_SECRET = re.compile(
    r"sk-(lf-|ant-|proj-)?[A-Za-z0-9_-]{16,}"       # Langfuse, Anthropic, OpenAI keys
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|gh[pousr]_[A-Za-z0-9]{36,}"                  # GitHub tokens
    r"|AKIA[0-9A-Z]{16}"                            # AWS access key id
    r"|AIza[0-9A-Za-z_-]{35}"                       # Google API key
    r"|xox[abpr]-[A-Za-z0-9-]{10,}")                # Slack tokens

PROMPT = """You are an independent reviewer. Another AI model produced the work below. Judge
whether it does what the task asked. Never modify anything.

To check claims you may run ONLY these shell commands in the current directory: {allowed}.
You may also use the read-only MCP tools (jcodemunch, jdocmunch, serena lookups). Any other
command (python, pytest, bash, sed, find, ...) is blocked and ends your turn with no answer,
so reason from the text instead.

Look for: requirements the work misses, code that cannot run or does not do what it claims,
claims that are false, and risks a careful reviewer would raise. Do not comment on style.
Report only what you can point to.

TASK:
{task}

WORK:
{work}

Reply with ONLY a JSON object, no prose before or after:
{{"verdict": "pass" | "fail" | "unsure",
  "findings": [{{"severity": "high" | "medium" | "low", "where": "file:line or empty",
                "problem": "what is wrong", "evidence": "what you checked"}}],
  "summary": "one sentence"}}
Use "unsure" when you could not check enough to decide."""


class RefereeInputError(ValueError):
    pass


def _allowed_commands() -> str:
    """The shell commands agy's allow list permits, e.g. "ls, cat, git diff"."""
    rules = json.loads((_REPO / "features/antigravity/permissions.json").read_text())
    return ", ".join(r[len("command("):-1] for r in rules["allow"] if r.startswith("command("))


def collect_work(cwd: str, diff: str = None, files=(), work_file: str = None) -> str:
    """Gather the work to judge. Raises RefereeInputError on refused or empty input."""
    parts = []
    if diff is not None:
        cmd = ["git", "-C", cwd, "diff"] + ([diff] if diff else [])
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RefereeInputError(f"git diff failed: {proc.stderr.strip()}")
        names = subprocess.run(cmd + ["--name-only"], capture_output=True, text=True).stdout.split()
        for name in names:
            if _CRED_PATH.search(name):
                raise RefereeInputError(f"diff touches a credential-like path: {name}")
        if proc.stdout.strip():
            parts.append(proc.stdout)
    for name in list(files) + ([work_file] if work_file else []):
        if _CRED_PATH.search(name):
            raise RefereeInputError(f"refusing credential-like path: {name}")
        path = Path(cwd, name)
        parts.append(f"===== {name} =====\n{path.read_text(encoding='utf-8')}")
    work = "\n".join(parts)
    if not work.strip():
        raise RefereeInputError("nothing to judge (empty diff and no files)")
    return work


def _extract_json(text: str):
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def _validate(data) -> str:
    """Return an error message, or '' when `data` is a well-formed verdict."""
    if not isinstance(data, dict):
        return "reply is not a JSON verdict"
    if data.get("verdict") not in VERDICTS:
        return f"unknown verdict {data.get('verdict')!r}"
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        return "findings is not a list"
    for f in findings:
        if not isinstance(f, dict) or not f.get("problem") or f.get("severity") not in SEVERITIES:
            return f"malformed finding: {f!r}"
    return ""


def _log(log_path, out: dict, seconds: float):
    if not log_path:
        return
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "verdict": out["verdict"],
            "findings": len(out.get("findings", [])),
            "high": sum(1 for f in out.get("findings", []) if f.get("severity") == "high"),
            "seconds": round(seconds, 1)}
    if out.get("error"):
        line["error"] = out["error"][:120]
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError as e:
        print(f"referee: could not write log {log_path}: {e}", file=sys.stderr)


def referee(task: str, work: str, cwd: str, agy_bin: str = None, timeout: int = DEFAULT_TIMEOUT,
            model: str = DEFAULT_MODEL, log_path="default") -> dict:
    if log_path == "default":
        env = os.environ.get("REFEREE_LOG")
        log_path = None if env == "" else (env or _REPO / "state" / "referee.jsonl")
    start = time.monotonic()
    out = _judge(task, work, cwd, agy_bin, timeout, model)
    _log(log_path, out, time.monotonic() - start)
    return out


def _judge(task, work, cwd, agy_bin, timeout, model) -> dict:
    if (model or "").lower().startswith("claude"):
        return {"verdict": "error", "error": f"{model} is the same provider as the work's author; "
                                             "use a gemini-* model"}
    size = len(work) + len(task)
    if size > MAX_WORK_CHARS:
        return {"verdict": "error", "error": f"task + work is {size} chars, over {MAX_WORK_CHARS}; "
                                             "narrow it (fewer files, a smaller diff range)"}
    if _SECRET.search(work) or _SECRET.search(task):
        return {"verdict": "error", "error": "input looks like it contains a secret; not sent"}
    res = ask_agy.ask(PROMPT.format(task=task, work=work, allowed=_allowed_commands()),
                      agy_bin=agy_bin, cwd=cwd,
                      edits=False, timeout=timeout, model=model)
    if not res.get("ok"):
        return {"verdict": "error", "error": f"agy: {res.get('error')}",
                "tool_errors": res.get("tool_errors", [])}
    data = _extract_json(res["response"])
    problem = _validate(data)
    if problem:
        return {"verdict": "error", "error": problem, "raw": res["response"][:2000]}
    out = {"verdict": data["verdict"], "findings": data.get("findings", []),
           "summary": data.get("summary", "")}
    if out["verdict"] == "pass" and any(f["severity"] == "high" for f in out["findings"]):
        out["verdict"] = "unsure"
        out["note"] = "downgraded from pass: the referee reported a high-severity finding"
    return out


def exit_code(out: dict) -> int:
    return EXIT.get(out["verdict"], 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task")
    ap.add_argument("--task-file")
    ap.add_argument("--diff", nargs="?", const="", default=None,
                    help="judge `git diff [REV]` (no REV: unstaged changes)")
    ap.add_argument("--file", action="append", default=[], help="judge this file (repeatable)")
    ap.add_argument("--work-file", help="judge the text in this file (a plan, an answer)")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--agy-bin")
    ap.add_argument("--no-log", action="store_true")
    args = ap.parse_args(argv)
    if not (args.task or args.task_file):
        ap.error("--task or --task-file is required")
    try:
        if args.task_file and _CRED_PATH.search(args.task_file):
            raise RefereeInputError(f"refusing credential-like path: {args.task_file}")
        task = Path(args.task_file).read_text(encoding="utf-8") if args.task_file else args.task
        work = collect_work(args.cwd, diff=args.diff, files=args.file, work_file=args.work_file)
    except (RefereeInputError, OSError) as e:
        print(json.dumps({"verdict": "error", "error": str(e)}, indent=2))
        return 1
    out = referee(task, work, cwd=args.cwd, agy_bin=args.agy_bin, timeout=args.timeout,
                  model=args.model, log_path=None if args.no_log else "default")
    print(json.dumps(out, indent=2))
    return exit_code(out)


if __name__ == "__main__":
    sys.exit(main())
