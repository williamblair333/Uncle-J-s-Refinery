"""Tests for scripts/ask-local-up.sh: it starts the backend config/ask_local.env names.

Each test builds a throwaway project tree (the script, a fake ollama-up.sh, a compose
file pointing at a temp models dir) and puts stub docker/dcup/curl first on PATH, so
no real container is touched. Stubs append their argv to calls.log.
"""
import os
import shutil
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
SCRIPT = _REPO / "scripts" / "ask-local-up.sh"


def _tree(tmp_path, config=None, gguf=True, dcup=True):
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "ask-local-up.sh")
    log = tmp_path / "calls.log"
    (root / "scripts" / "ollama-up.sh").write_text(
        f'echo "ollama-up URL=$ASK_LOCAL_URL MODEL=$ASK_LOCAL_MODEL" >> {log}\n')
    models = tmp_path / "models"
    models.mkdir()
    if gguf:
        (models / "m.gguf").write_text("x")
    (root / "docker" / "llama-heretic").mkdir(parents=True)
    (root / "docker" / "llama-heretic" / "compose.yaml").write_text(
        f"services:\n  llama-heretic:\n    volumes:\n      - {models}:/models:ro\n")
    if config is not None:
        (root / "config").mkdir()
        (root / "config" / "ask_local.env").write_text(config)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    names = ["docker", "curl"] + (["dcup"] if dcup else [])
    for name in names:
        stub = bin_dir / name
        stub.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> {log}\n')
        stub.chmod(0o755)
    return root, bin_dir, log


def _run(root, bin_dir, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ASK_LOCAL_")}
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env.update(extra)
    return subprocess.run(["bash", str(root / "scripts" / "ask-local-up.sh")], env=env,
                          text=True, capture_output=True)


def _calls(log):
    return log.read_text().splitlines() if log.exists() else []


def test_no_config_runs_ollama_up_with_the_old_defaults(tmp_path):
    root, bin_dir, log = _tree(tmp_path)
    r = _run(root, bin_dir)
    assert r.returncode == 0, r.stderr
    assert _calls(log) == ["ollama-up URL=http://127.0.0.1:11434 MODEL=qwen3.5:9b"]


def test_ollama_backend_passes_the_configured_model_on(tmp_path):
    root, bin_dir, log = _tree(tmp_path, "ASK_LOCAL_BACKEND=ollama\nASK_LOCAL_MODEL=granite4.2:8b\n")
    r = _run(root, bin_dir)
    assert r.returncode == 0, r.stderr
    assert _calls(log) == ["ollama-up URL=http://127.0.0.1:11434 MODEL=granite4.2:8b"]


def test_openai_backend_starts_heretic_through_dcup(tmp_path):
    # Only BACKEND set: the missing URL/MODEL keys must not trip set -e.
    root, bin_dir, log = _tree(tmp_path, "ASK_LOCAL_BACKEND=openai\n")
    r = _run(root, bin_dir)
    assert r.returncode == 0, r.stderr
    compose = root / "docker" / "llama-heretic" / "compose.yaml"
    calls = _calls(log)
    assert calls[0] == f"dcup up -f {compose} -d"
    assert calls[1].startswith("curl ") and calls[1].endswith("http://127.0.0.1:8090/health")
    assert not any(c.startswith("ollama-up") for c in calls)
    assert "llama-heretic ready" in r.stdout


def test_openai_without_dcup_uses_docker_compose(tmp_path):
    root, bin_dir, log = _tree(tmp_path, "ASK_LOCAL_BACKEND=openai\n", dcup=False)
    r = _run(root, bin_dir, DCUP_FALLBACK=str(tmp_path / "no-dcup"))
    assert r.returncode == 0, r.stderr
    compose = root / "docker" / "llama-heretic" / "compose.yaml"
    assert _calls(log)[0] == f"docker compose -f {compose} up -d"


def test_env_overrides_the_file(tmp_path):
    root, bin_dir, log = _tree(tmp_path, "ASK_LOCAL_BACKEND=openai\n")
    r = _run(root, bin_dir, ASK_LOCAL_BACKEND="ollama")
    assert r.returncode == 0, r.stderr
    assert _calls(log)[0].startswith("ollama-up ")


def test_missing_gguf_refuses_without_starting_anything(tmp_path):
    root, bin_dir, log = _tree(tmp_path, "ASK_LOCAL_BACKEND=openai\n", gguf=False)
    r = _run(root, bin_dir)
    assert r.returncode == 1
    assert "no .gguf" in r.stderr
    assert _calls(log) == []


def test_unknown_backend_is_refused(tmp_path):
    root, bin_dir, log = _tree(tmp_path, "ASK_LOCAL_BACKEND=vllm\n")
    r = _run(root, bin_dir)
    assert r.returncode == 1
    assert "vllm is not ollama or openai" in r.stderr
    assert _calls(log) == []
