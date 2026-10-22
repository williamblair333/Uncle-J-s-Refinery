"""scripts/heretic.sh: `up` goes through dcup when installed; everything else is docker compose.

Stub dcup/docker on PATH record their argv, so no container is touched.
"""
import os
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
SCRIPT = _REPO / "scripts" / "heretic.sh"
COMPOSE = _REPO / "docker" / "llama-heretic" / "compose.yaml"


def _run(tmp_path, args, dcup=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    for name in ["docker"] + (["dcup"] if dcup else []):
        stub = bin_dir / name
        stub.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> {log}\n')
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
           "DCUP_FALLBACK": str(tmp_path / "no-dcup")}
    subprocess.run(["bash", str(SCRIPT), *args], env=env, check=True)
    return log.read_text().splitlines()


def test_up_goes_through_dcup(tmp_path):
    assert _run(tmp_path, ["up", "-d"]) == [f"dcup up -f {COMPOSE} -d"]


def test_other_subcommands_use_docker_compose(tmp_path):
    assert _run(tmp_path, ["logs", "--tail", "5"]) == [f"docker compose -f {COMPOSE} logs --tail 5"]
    assert _run(tmp_path, ["down"])[-1] == f"docker compose -f {COMPOSE} down"


def test_up_without_dcup_falls_back_to_compose(tmp_path):
    assert _run(tmp_path, ["up", "-d"], dcup=False) == [f"docker compose -f {COMPOSE} up -d"]
