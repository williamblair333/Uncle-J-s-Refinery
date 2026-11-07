#!/usr/bin/env python3
"""`just ram-bench`: does a job loading Ollama slow Heretic, and does stopping Ollama fix it?

Sends one fixed uncached prompt to Heretic at each stage and samples memory and disk reads every
5 s. It waits for a scheduled job to load Ollama and never starts one: a hand-run Klarheit trial
would count against its slots. Ollama is stopped only when no Klarheit job is running.

Stages: baseline, during (model loaded), after-job (job ended, model still loaded),
recovered (model stopped, then a settle wait).
"""
from __future__ import annotations

import argparse
import http.client
import json
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERETIC = "http://127.0.0.1:8090"
OLLAMA = "http://127.0.0.1:11434"
STATE = Path(__file__).resolve().parent.parent / "state" / "ram-bench"
PROMPT = " ".join(f"item {i} of the fixed bench list;" for i in range(200))
SAMPLE_SECONDS = 5
SLOW_RATIO = 0.75
# Every job that uses Ollama. Stopping it under any of these costs a slot for good.
OLLAMA_JOBS = ("klarheit-rv.service", "klarheit-cycle.service", "klarheit-m12.service")
HTTP_ERRORS = (OSError, ValueError, http.client.HTTPException)


def http_json(url: str, body: dict | None = None, timeout: float = 5) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def meminfo_available_gb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return round(int(line.split()[1]) / 1024**2, 2)
    return 0.0


def heretic_rss_gb() -> float | None:
    pids = subprocess.run(["pgrep", "-o", "llama-server"], capture_output=True, text=True).stdout.split()
    if not pids:
        return None
    try:
        for line in Path(f"/proc/{pids[0]}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024**2, 2)
    except OSError:
        pass
    return None


def disk_sectors_read(disk: str) -> int:
    for line in Path("/proc/diskstats").read_text().splitlines():
        parts = line.split()
        if parts[2] == disk:
            return int(parts[5])
    return 0


def ollama_models() -> list[str]:
    try:
        return [m["name"] for m in http_json(f"{OLLAMA}/api/ps").get("models", [])]
    except HTTP_ERRORS:
        return []


def job_running(service: str) -> bool:
    """Only a clear "stopped" counts as stopped: a systemctl error must not free Ollama to be stopped."""
    out = subprocess.run(
        ["systemctl", "--user", "is-active", service], capture_output=True, text=True
    ).stdout.strip()
    return out not in {"inactive", "failed"}


def running_jobs(jobs=OLLAMA_JOBS, is_running=job_running) -> list[str]:
    return [job for job in jobs if is_running(job)]


def heretic_prompt() -> dict:
    """One fixed prompt, uncached, so each stage pays the full prompt cost."""
    started = time.monotonic()
    body = {"prompt": PROMPT, "n_predict": 32, "cache_prompt": False, "temperature": 0, "seed": 1}
    try:
        timings = http_json(f"{HERETIC}/completion", body, timeout=600).get("timings", {})
    except HTTP_ERRORS as exc:
        return {"error": str(exc), "wall_s": round(time.monotonic() - started, 1)}
    if not timings.get("prompt_per_second"):
        return {"error": "reply had no timings", "wall_s": round(time.monotonic() - started, 1)}
    return {
        "wall_s": round(time.monotonic() - started, 1),
        "prompt_tokens": timings.get("prompt_n"),
        "prompt_tps": round(timings.get("prompt_per_second") or 0, 1),
        "gen_tps": round(timings.get("predicted_per_second") or 0, 1),
    }


def summarize(results: list[dict]) -> list[str]:
    """Each stage against the first good baseline; SLOW means 25% or more below it."""
    base = next((r for r in results if r["stage"] == "baseline" and r.get("prompt_tps")), None)
    lines = []
    for r in results:
        if "error" in r:
            lines.append(f"{r['stage']:<10} failed: {r['error']}")
            continue
        ratio = r["prompt_tps"] / base["prompt_tps"] if base else None
        flag = "  SLOW" if ratio is not None and ratio <= SLOW_RATIO else ""
        rel = f"{ratio:.2f}x" if ratio is not None else "n/a"
        lines.append(
            f"{r['stage']:<10} prompt {r['prompt_tps']:>7} t/s ({rel}) gen {r['gen_tps']:>5} t/s "
            f"wall {r['wall_s']:>6}s heretic {r.get('rss_gb')} GB avail {r.get('avail_gb')} GB "
            f"ollama {r.get('ollama')}{flag}"
        )
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--service", default="klarheit-rv.service", help="the job expected to load Ollama")
    ap.add_argument("--wait", type=int, default=1500, help="seconds to wait for Ollama to load")
    ap.add_argument("--job-timeout", type=int, default=2400, help="seconds to wait for the job to end")
    ap.add_argument("--settle", type=int, default=120, help="seconds between stopping Ollama and the last prompt")
    ap.add_argument("--disk", default="sda")
    args = ap.parse_args()

    if ollama_models():
        print("ollama already loaded: no clean baseline, stopping", file=sys.stderr)
        return 2

    STATE.mkdir(parents=True, exist_ok=True)
    log = STATE / f"{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    done = threading.Event()

    def sampler() -> None:
        last = disk_sectors_read(args.disk)
        with log.open("a") as fh:
            while not done.wait(SAMPLE_SECONDS):
                now = disk_sectors_read(args.disk)
                row = {
                    "t": datetime.now().isoformat(timespec="seconds"),
                    "rss_gb": heretic_rss_gb(),
                    "avail_gb": meminfo_available_gb(),
                    "read_mb_s": round((now - last) * 512 / 1e6 / SAMPLE_SECONDS, 1),
                    "ollama": ollama_models(),
                }
                last = now
                fh.write(json.dumps(row) + "\n")
                fh.flush()

    threading.Thread(target=sampler, daemon=True).start()
    results: list[dict] = []

    def stage(name: str) -> None:
        # What was loaded right after the prompt, since a label alone can be wrong: the job may have
        # ended before "during", or something may have reloaded the model before "recovered".
        r = {
            "stage": name,
            **heretic_prompt(),
            "rss_gb": heretic_rss_gb(),
            "avail_gb": meminfo_available_gb(),
            "ollama": ollama_models(),
        }
        results.append(r)
        print(json.dumps(r), flush=True)

    print(f"log: {log}", flush=True)
    stage("baseline")
    stage("baseline")

    print(f"waiting up to {args.wait}s for {args.service} to load Ollama", flush=True)
    deadline = time.monotonic() + args.wait
    while not ollama_models() and time.monotonic() < deadline:
        time.sleep(SAMPLE_SECONDS)
    models = ollama_models()
    if not models:
        print("no Ollama load seen", flush=True)
    else:
        print(f"loaded: {models} at {datetime.now():%H:%M:%S}", flush=True)
        time.sleep(60)
        stage("during")

        deadline = time.monotonic() + args.job_timeout
        while job_running(args.service) and time.monotonic() < deadline:
            time.sleep(SAMPLE_SECONDS)
        if job_running(args.service):
            print(f"{args.service} still running: leaving Ollama alone", flush=True)
        else:
            stage("after-job")
            busy = running_jobs()
            if busy:
                print(f"{busy} running: leaving Ollama alone", flush=True)
            else:
                for model in ollama_models():
                    subprocess.run(["docker", "exec", "ollama", "ollama", "stop", model], check=False)
                print(f"stopped Ollama models, settling {args.settle}s", flush=True)
                time.sleep(args.settle)
                stage("recovered")

    done.set()
    print("\n".join(summarize(results)), flush=True)
    print(f"samples: {log}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
