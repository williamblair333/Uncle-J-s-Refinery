#!/usr/bin/env python3
"""First-run gate: prove a project installs and does its core job on a clean machine.

Reads the `verify:` block from a project's PRODUCT.md, runs the documented install
steps and the core task inside a throwaway container, and asserts observable side
effects. Exit codes alone never pass: a CLI that catches an exception, prints a
friendly message and exits 0 is the failure this gate exists to catch.

Usage:
    first_run_gate.py [PROJECT_DIR] [--json] [--keep]

Exit status: 0 pass, 1 fail, 2 could not run (treated as a block by the hooks).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

DEFAULT_IMAGE = "debian:bookworm-slim"
REPORT_DIR = ".first-run-gate"
STATE_PASS, STATE_FAIL, STATE_BLOCKED = "pass", "fail", "blocked"


class GateError(Exception):
    """Gate could not run. Not a pass and not a code failure."""


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def load_verify(project: Path) -> dict:
    product = project / "PRODUCT.md"
    if not product.exists():
        raise GateError("no PRODUCT.md — write one with the product-brief skill")
    text = product.read_text(encoding="utf-8", errors="replace")
    for block in re.findall(r"```ya?ml\n(.*?)```", text, re.S):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError as exc:
            raise GateError(f"PRODUCT.md yaml block does not parse: {exc}") from exc
        if isinstance(data, dict) and "verify" in data:
            return data["verify"] or {}
    raise GateError("PRODUCT.md has no ```yaml block containing a `verify:` key")


def validate(verify: dict) -> tuple[list[str], str, list[dict], int | None]:
    install = verify.get("install") or []
    core = verify.get("run")
    expect = verify.get("expect") or []
    if not core:
        raise GateError("verify.run is required — name the core task command")
    if not isinstance(install, list) or not all(isinstance(s, str) for s in install):
        raise GateError("verify.install must be a list of shell commands")

    normalized: list[dict] = []
    for item in expect:
        if not isinstance(item, dict) or len(item) != 1:
            raise GateError(f"each verify.expect entry is a single key: {item!r}")
        (kind, value), = item.items()
        if kind not in {"file", "stdout_contains", "stderr_contains", "exit_code"}:
            raise GateError(f"unsupported expectation: {kind}")
        normalized.append({"kind": kind, "value": value})

    observable = [e for e in normalized if e["kind"] != "exit_code"]
    if not observable:
        raise GateError(
            "verify.expect needs at least one observable proof (file / stdout_contains). "
            "exit_code alone cannot distinguish success from a handled error that exits 0"
        )

    # The proof must come from the program, not from the test. `run: cmd; echo done`
    # with `expect: stdout_contains: done` passes while the program fails — the exact
    # false green this gate exists to catch, one level up.
    echoed = " ".join(re.findall(r"\b(?:echo|printf)\b([^;|&]*)", core))
    for item in normalized:
        if item["kind"] in {"stdout_contains", "stderr_contains"} and str(item["value"]) in echoed:
            raise GateError(
                f"verify.run echoes the expected string {item['value']!r} itself — "
                "that expectation would prove the echo ran, not the project. "
                "Assert on output the program produces."
            )
    return install, core, normalized, verify.get("time_target_seconds")


def find_readme(project: Path) -> Path | None:
    """Any casing counts. `Readme.md` is a README to a human, so it is one here —
    matching only the shouty spelling filed a real project as undocumented."""
    for entry in sorted(project.iterdir()) if project.is_dir() else []:
        if entry.is_file() and entry.name.lower() in {"readme.md", "readme", "readme.rst", "readme.txt"}:
            return entry
    return None


def docs_drift(project: Path, install: list[str]) -> list[str]:
    """Install steps must appear in the README a stranger would actually read."""
    readme = find_readme(project)
    if readme is None:
        return []
    text = readme.read_text(encoding="utf-8", errors="replace")
    return [step for step in install if step.strip() not in text]


def docker_available() -> None:
    if shutil.which("docker") is None:
        raise GateError("docker not found — gate cannot run on this host")
    probe = run(["docker", "info"], timeout=60)
    if probe.returncode != 0:
        raise GateError(f"docker not usable: {probe.stderr.strip()[:200]}")


def ensure_image(image: str) -> float:
    """Pull separately so cold-pull time is visible but not charged to the user."""
    if run(["docker", "image", "inspect", image], timeout=60).returncode == 0:
        return 0.0
    start = time.monotonic()
    pull = run(["docker", "pull", image], timeout=900)
    if pull.returncode != 0:
        raise GateError(f"cannot pull {image}: {pull.stderr.strip()[:200]}")
    return round(time.monotonic() - start, 1)


EXCLUDES = (
    ".git",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    REPORT_DIR,
)


def copy_project(project: Path, cid: str) -> str | None:
    """Stream a filtered tar into the container. Returns an error string, or None."""
    tar_cmd = ["tar", "-cf", "-"]
    for pattern in EXCLUDES:
        tar_cmd += ["--exclude", pattern]
    tar_cmd += ["-C", str(project), "."]
    try:
        with subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as tar:
            loaded = subprocess.run(
                ["docker", "cp", "-", f"{cid}:/work"],
                stdin=tar.stdout,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if tar.stdout:
                tar.stdout.close()
            tar_err = tar.stderr.read().decode(errors="replace") if tar.stderr else ""
    except (OSError, subprocess.SubprocessError) as exc:
        return f"copy into container failed: {exc}"
    if loaded.returncode != 0:
        return f"copy into container failed: {loaded.stderr.strip()[:200]}"
    if tar.returncode not in (0, None):
        return f"could not archive the project: {tar_err.strip()[:200]}"
    return None


def gate(project: Path, keep: bool = False) -> dict:
    verify = load_verify(project)
    install, core, expect, target = validate(verify)
    image = verify.get("image", DEFAULT_IMAGE)
    network = verify.get("network", "required")
    if network not in {"required", "none"}:
        raise GateError("verify.network must be 'required' or 'none'")

    docker_available()
    pull_seconds = ensure_image(image)

    head = run(["git", "-C", str(project), "rev-parse", "HEAD"], timeout=30)
    report: dict = {
        "project": str(project),
        "image": image,
        "network": network,
        "git_head": head.stdout.strip() if head.returncode == 0 else None,
        "image_pull_seconds": pull_seconds,
        "stages": [],
        "failures": [],
        "warnings": [],
        "state": STATE_FAIL,
    }

    # Drift is a failure unless the brief declares WHY it runs a different path —
    # e.g. the documented path is `docker compose`, which cannot nest inside the
    # gate's own container. The reason is required and is printed in the report,
    # so an exception is disclosed rather than silent.
    install_note = verify.get("install_note")
    drift = docs_drift(project, install)
    for step in drift:
        if install_note:
            report["warnings"].append(
                {
                    "kind": "docs_drift_declared",
                    "detail": f"not the documented step ({step}) — declared reason: {install_note}",
                }
            )
        else:
            report["failures"].append(
                {"kind": "docs_drift", "detail": f"install step is not in the README: {step}"}
            )

    args = ["docker", "run", "-d", "--rm"]
    if network == "none":
        args += ["--network", "none"]
    args += ["-w", "/work", image, "sleep", "1800"]
    started = run(args, timeout=120)
    if started.returncode != 0:
        raise GateError(f"container did not start: {started.stderr.strip()[:200]}")
    cid = started.stdout.strip()

    def exec_in(command: str, timeout: int = 900) -> subprocess.CompletedProcess:
        return run(["docker", "exec", cid, "sh", "-lc", command], timeout=timeout)

    try:
        # Copy the source in rather than mounting: the container must not be able to
        # write back into the working tree, and a mount would hide missing files that
        # a real user's fresh clone would not have. Secrets and build junk are excluded
        # — a project that needs real credentials to show its core job must ship a
        # documented stub mode instead.
        copy_failure = copy_project(project, cid)
        if copy_failure:
            raise GateError(copy_failure)

        for step in install:
            stage_start = time.monotonic()
            result = exec_in(step)
            report["stages"].append(
                {
                    "stage": "install",
                    "command": step,
                    "seconds": round(time.monotonic() - stage_start, 1),
                    "exit_code": result.returncode,
                }
            )
            if result.returncode != 0:
                report["failures"].append(
                    {
                        "kind": "install_failed",
                        "detail": f"`{step}` exited {result.returncode}",
                        "stderr": result.stderr.strip()[-800:],
                    }
                )
                return finish(report, target)

        core_start = time.monotonic()
        core_result = exec_in(core)
        core_seconds = round(time.monotonic() - core_start, 1)
        report["stages"].append(
            {
                "stage": "core_task",
                "command": core,
                "seconds": core_seconds,
                "exit_code": core_result.returncode,
            }
        )
        report["core_stdout_tail"] = core_result.stdout.strip()[-800:]
        report["core_stderr_tail"] = core_result.stderr.strip()[-800:]

        for item in expect:
            kind, value = item["kind"], item["value"]
            if kind == "exit_code":
                if core_result.returncode != value:
                    report["failures"].append(
                        {"kind": "exit_code", "detail": f"expected {value}, got {core_result.returncode}"}
                    )
            elif kind == "stdout_contains":
                if str(value) not in core_result.stdout:
                    report["failures"].append(
                        {"kind": "stdout_contains", "detail": f"stdout does not contain {value!r}"}
                    )
            elif kind == "stderr_contains":
                if str(value) not in core_result.stderr:
                    report["failures"].append(
                        {"kind": "stderr_contains", "detail": f"stderr does not contain {value!r}"}
                    )
            elif kind == "file":
                probe = exec_in(f"test -s '{value}'", timeout=60)
                if probe.returncode != 0:
                    report["failures"].append(
                        {"kind": "file", "detail": f"{value} missing or empty after the core task"}
                    )

        report["time_to_first_result_seconds"] = round(
            sum(s["seconds"] for s in report["stages"]), 1
        )
        return finish(report, target)
    finally:
        if keep:
            report["container"] = cid
        else:
            run(["docker", "rm", "-f", cid], timeout=120)


def finish(report: dict, target: int | None) -> dict:
    ttfr = report.get("time_to_first_result_seconds")
    if ttfr is None:
        report["time_to_first_result_seconds"] = round(
            sum(s["seconds"] for s in report["stages"]), 1
        )
        ttfr = report["time_to_first_result_seconds"]
    if target and ttfr > target:
        # Warns, never blocks: slow is a product problem, broken is a gate problem.
        report["warnings"].append(
            {"kind": "time_target", "detail": f"{ttfr}s exceeds target {target}s"}
        )
    report["state"] = STATE_PASS if not report["failures"] else STATE_FAIL
    return report


def write_report(project: Path, report: dict) -> Path:
    out_dir = project / REPORT_DIR
    out_dir.mkdir(exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"# First-run gate — {report['state'].upper()}",
        "",
        f"- project: `{report['project']}`",
        f"- image: `{report['image']}` (network: {report['network']})",
        f"- time to first result: {report.get('time_to_first_result_seconds', '?')}s"
        f" (image pull {report.get('image_pull_seconds', 0)}s, excluded)",
        "",
    ]
    if report["failures"]:
        lines += ["## Failures", ""]
        lines += [f"- **{f['kind']}** — {f['detail']}" for f in report["failures"]] + [""]
    if report["warnings"]:
        lines += ["## Warnings", ""]
        lines += [f"- {w['kind']} — {w['detail']}" for w in report["warnings"]] + [""]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return out_dir / "report.json"


CHECK_OUTPUT = Path("/tmp/first-run-gate-check.json")


def check_brief(project: Path, as_json: bool = False) -> int:
    """Validate a brief without Docker: parse, validate, and report drift.

    This is the half of the gate that answers "is this brief runnable at all",
    which is worth knowing before paying for a container — and is what the gate
    itself is verified on, since it cannot run Docker inside Docker.
    """
    result: dict = {"project": str(project), "checks": []}
    try:
        verify = load_verify(project)
        install, core, expect, target = validate(verify)
    except GateError as exc:
        result["state"] = STATE_BLOCKED
        result["reason"] = str(exc)
        CHECK_OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2) if as_json else f"BRIEF NOT RUNNABLE — {exc}")
        return 2

    result["checks"].append({"verify_block": "parsed"})
    result["checks"].append({"core_task": core})
    result["checks"].append(
        {"observable_expectations": len([e for e in expect if e["kind"] != "exit_code"])}
    )
    drift = docs_drift(project, install)
    if drift:
        result["checks"].append({"docs_drift": drift})
    result["time_target_seconds"] = target
    result["state"] = STATE_FAIL if drift else STATE_PASS
    CHECK_OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if as_json:
        print(json.dumps(result, indent=2))
    elif drift:
        print("brief is NOT runnable as documented — install steps missing from the README:")
        for step in drift:
            print(f"  - {step}")
    else:
        print(f"brief is runnable — core task: {core}")
    return 0 if result["state"] == STATE_PASS else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", default=".", help="project directory")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--keep", action="store_true", help="leave the container running")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the brief's verify block without running containers",
    )
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if args.check:
        return check_brief(project, as_json=args.json)
    try:
        report = gate(project, keep=args.keep)
    except GateError as exc:
        blocked = {"project": str(project), "state": STATE_BLOCKED, "reason": str(exc)}
        if args.json:
            print(json.dumps(blocked, indent=2))
        else:
            print(f"BLOCKED — {exc}", file=sys.stderr)
        if (project / "PRODUCT.md").exists():
            write_report(project, {**blocked, "failures": [], "warnings": [], "stages": []})
        return 2

    path = write_report(project, report)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{report['state'].upper()} — report: {path}")
        for failure in report["failures"]:
            print(f"  FAIL {failure['kind']}: {failure['detail']}")
        for warning in report["warnings"]:
            print(f"  WARN {warning['kind']}: {warning['detail']}")
    return 0 if report["state"] == STATE_PASS else 1


if __name__ == "__main__":
    sys.exit(main())
