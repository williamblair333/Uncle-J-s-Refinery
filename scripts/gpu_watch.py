#!/usr/bin/env python3
"""Warn when a GPU container loses the GPU or Ollama runs a model on CPU.

Why: on 2026-11-24 the host Ollama lost the GPU (NVIDIA toolkit + systemctl
daemon-reload) and ran a 9B on CPU in host RAM beside Heretic and a VM; dma64 froze.
The containers now use CDI, which survives a daemon-reload; this catches a relapse.

  gpu_watch.py --check   print findings; exit 0 ok/na, 1 problem, 2 couldn't check
  gpu_watch.py --cron    same, plus one Telegram message when the problems change
                         (and one on recovery). State: state/gpu-watch.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "gpu-watch.json"


@dataclass
class Result:
    state: str = "ok"                 # ok | problem | na | unknown
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    restart: list[str] = field(default_factory=list)   # containers to restart


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def _gpu_driver(requests_json: str) -> str | None:
    try:
        reqs = json.loads(requests_json or "null") or []
    except json.JSONDecodeError:
        return None
    for r in reqs:
        caps = [c for group in (r.get("Capabilities") or []) for c in group]
        if "gpu" in caps or r.get("Driver") in ("nvidia", "cdi"):
            return r.get("Driver") or "unknown"
    return None


def _ollama_cpu_rows(ps: str) -> list[str]:
    """Rows of `ollama ps` whose PROCESSOR column mentions CPU. The column is cut at the
    header's offsets (values like "100% GPU" contain spaces, sizes may be GB or MB)."""
    lines = [ln for ln in ps.splitlines() if ln.strip()]
    if not lines or "PROCESSOR" not in lines[0]:
        return []
    head = lines[0]
    start = head.index("PROCESSOR")
    nxt = [head.find(c, start) for c in ("CONTEXT", "UNTIL") if head.find(c, start) > 0]
    end = min(nxt) if nxt else None
    out = []
    for line in lines[1:]:
        proc = line[start:end].strip()
        if "CPU" in proc:
            out.append(f"ollama runs {line.split()[0]} on {proc} (host RAM, not VRAM)")
    return out


def check(run=run_cmd) -> Result:
    res = Result()
    rc, out = run(["nvidia-smi", "-L"])
    if rc == 127 and "No such file" in out:
        res.state = "na"             # no NVIDIA driver installed: not applicable
        return res
    if rc != 0:
        res.state = "unknown"        # a GPU host whose driver fails is not "no GPU"
        res.notes.append(f"host nvidia-smi failed: {out[:120]}")
        return res
    rc, out = run(["docker", "ps", "--format", "{{.Names}}"])
    if rc != 0:
        res.state = "unknown"
        res.notes.append(f"docker ps failed: {out[:120]}")
        return res
    for name in [n for n in out.splitlines() if n.strip()]:
        _, reqs = run(["docker", "inspect", "-f", "{{json .HostConfig.DeviceRequests}}", name])
        driver = _gpu_driver(reqs)
        if driver is None:
            continue
        if driver == "nvidia":
            res.notes.append(f"{name} uses driver: nvidia; a daemon-reload can drop its GPU (use CDI)")
        rc, smi = run(["docker", "exec", name, "nvidia-smi", "-L"])
        if rc != 0 or "GPU " not in smi:
            first = (smi.splitlines() or ["no output"])[0][:100]
            res.problems.append(f"{name} can't see the GPU ({first})")
            res.restart.append(name)
            continue
        if name == "ollama":
            rc, ps = run(["docker", "exec", "ollama", "ollama", "ps"])
            if rc != 0 or "PROCESSOR" not in (ps.splitlines() or [""])[0]:
                res.notes.append(f"ollama ps unreadable (rc {rc}): {ps[:100]}")
                res.state = "unknown"    # can't tell CPU from GPU: don't report clean
            else:
                res.problems += _ollama_cpu_rows(ps)
    if res.problems:
        res.state = "problem"
    return res


def _message(res: Result) -> str:
    lines = ["dma64 GPU watch: a model is off the GPU — host RAM can run out (11-24 freeze)."]
    lines += [f"- {p}" for p in res.problems]
    for name in res.restart:
        lines.append(f"Fix: docker restart {name}")
    if any("ollama runs" in p for p in res.problems):
        lines.append("Fix: docker exec ollama ollama stop MODEL, then docker restart ollama")
    return "\n".join(lines)


def alert_on_change(res: Result, state_path: Path, send) -> bool:
    """Send one message when the problem set changes. The state is saved only after a
    successful send, so a failed alert is retried on the next run. True if it acted."""
    try:
        prev = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        prev = {"problems": []}
    if res.state not in ("ok", "problem"):
        return False                 # na/unknown: don't flap the state
    if res.problems == prev.get("problems", []):
        return False
    if res.problems:
        sent = send(_message(res))
    elif prev.get("problems"):
        sent = send("dma64 GPU watch: all GPU containers are back on the GPU.")
    else:
        sent = True
    if not sent:
        print("gpu-watch: Telegram alert not sent; will retry next run", file=sys.stderr)
        return True
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"problems": res.problems}))
    return True


def telegram(text: str) -> bool:
    """Send via lib/notify.sh (parse_mode HTML, so escape) with .env loaded."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    script = ('set -a; source "$1/.env"; set +a; '
              '[ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] && '
              'source "$1/lib/notify.sh" && notify_send_text "$2"')
    rc, _ = run_cmd(["bash", "-c", script, "_", str(ROOT), text])
    return rc == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="print findings only (default)")
    mode.add_argument("--cron", action="store_true", help="also alert on change")
    args = ap.parse_args(argv)
    res = check()
    # Under cron, log only when something changed (it runs 288 times a day).
    if args.cron and not alert_on_change(res, STATE, telegram):
        return {"ok": 0, "na": 0, "problem": 1}.get(res.state, 2)
    if args.cron:
        print(time.strftime("%F %T"), res.state)
    for p in res.problems:
        print(f"PROBLEM {p}")
    for n in res.notes:
        print(f"NOTE {n}")
    if res.state == "na":
        print("gpu-watch: no NVIDIA GPU on this host")
    elif res.state == "ok":
        print("gpu-watch: ok")
    return {"ok": 0, "na": 0, "problem": 1}.get(res.state, 2)


if __name__ == "__main__":
    sys.exit(main())
