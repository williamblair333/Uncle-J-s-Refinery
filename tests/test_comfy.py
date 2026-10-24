"""ComfyUI wrappers: scripts/comfy.sh (dcup routing), comfy-models.sh (sha256 gate),
comfy_job.py (workflow shape, history parsing, GPU notes). No container or GPU touched."""
import hashlib
import importlib.util
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "docker" / "comfyui" / "compose.yaml"
_spec = importlib.util.spec_from_file_location("comfy_job", REPO / "scripts" / "comfy_job.py")
cj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cj)


# ── comfy.sh ──────────────────────────────────────────────────────────────
def _run_comfy(tmp_path, args, dcup=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    for name in ["docker"] + (["dcup"] if dcup else []):
        stub = bin_dir / name
        stub.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> {log}\n')
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
           "DCUP_FALLBACK": str(tmp_path / "no-dcup"), "COMFY_OUTPUTS": str(tmp_path / "out")}
    subprocess.run(["bash", str(REPO / "scripts" / "comfy.sh"), *args], env=env, check=True)
    return log.read_text().splitlines()


def test_up_goes_through_dcup_and_makes_output_dir(tmp_path):
    assert _run_comfy(tmp_path, ["up", "-d"]) == [f"dcup up -f {COMPOSE} -d"]
    assert (tmp_path / "out").is_dir()


def test_other_subcommands_use_docker_compose(tmp_path):
    assert _run_comfy(tmp_path, ["logs", "-f"]) == [f"docker compose -f {COMPOSE} logs -f"]


def test_up_without_dcup_falls_back_to_compose(tmp_path):
    assert _run_comfy(tmp_path, ["up", "-d"], dcup=False) == [f"docker compose -f {COMPOSE} up -d"]


def test_compose_binds_loopback_only():
    ports = [line.strip() for line in COMPOSE.read_text().splitlines()
             if line.strip().startswith('- "') and ":8188" in line]
    assert ports == ['- "127.0.0.1:8188:8188"']


# ── comfy-models.sh ───────────────────────────────────────────────────────
def _fetch(tmp_path, files, existing=None):
    """files: {dest: (served bytes, sha in the LFS pointer)}; curl is stubbed to read local
    files: src/resolve/<name> holds the bytes, src/raw/<name> the LFS pointer."""
    src = tmp_path / "src"
    (src / "resolve").mkdir(parents=True, exist_ok=True)
    (src / "raw").mkdir(exist_ok=True)
    lines = []
    for dest, (data, sha) in files.items():
        name = Path(dest).name
        (src / "resolve" / name).write_bytes(data)
        if sha is not None:
            (src / "raw" / name).write_text(
                f"version https://git-lfs.github.com/spec/v1\noid sha256:{sha}\nsize {len(data)}\n")
        lines.append(f"{dest} file://{src}/resolve/{name}")
    manifest = tmp_path / "models.txt"
    manifest.write_text("# comment\n\n" + "\n".join(lines) + "\n")
    root = tmp_path / "models"
    for dest, data in (existing or {}).items():
        (root / dest).parent.mkdir(parents=True, exist_ok=True)
        (root / dest).write_bytes(data)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    curl_log = tmp_path / "curl.log"
    # comfy-models.sh calls `curl ... <url>` for the pointer and `curl ... -o <out> <url>`
    (bin_dir / "curl").write_text(
        '#!/usr/bin/env bash\nargs=("$@"); n=${#args[@]}; src="${args[$((n-1))]#file://}"\n'
        'if [[ "${args[$((n-3))]}" == -o ]]; then\n'
        f'  cp "$src" "${{args[$((n-2))]}}"; echo curl >> {curl_log}\n'
        'else [[ -f "$src" ]] || exit 22; cat "$src"; fi\n')
    (bin_dir / "curl").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
           "COMFY_MODELS_MANIFEST": str(manifest), "MODELS_ROOT": str(root)}
    r = subprocess.run(["bash", str(REPO / "scripts" / "comfy-models.sh")], env=env,
                       capture_output=True, text=True)
    calls = curl_log.read_text().count("curl") if curl_log.exists() else 0
    return r, root, calls


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def test_fetch_verifies_and_renames(tmp_path):
    r, root, calls = _fetch(tmp_path, {"m/a.bin": (b"hello", _sha(b"hello"))})
    assert r.returncode == 0, r.stderr
    assert (root / "m/a.bin").read_bytes() == b"hello" and calls == 1


def test_fetch_mismatch_keeps_bad_file_aside(tmp_path):
    r, root, _ = _fetch(tmp_path, {"m/a.bin": (b"evil", _sha(b"hello"))})
    assert r.returncode == 1 and "MISMATCH" in r.stderr
    assert not (root / "m/a.bin").exists() and (root / "m/a.bin.part.bad").exists()


def test_existing_good_file_is_not_refetched(tmp_path):
    r, _, calls = _fetch(tmp_path, {"m/a.bin": (b"hello", _sha(b"hello"))},
                         existing={"m/a.bin": b"hello"})
    assert r.returncode == 0 and calls == 0 and "ok" in r.stdout


def test_existing_bad_file_fails_and_is_left_alone(tmp_path):
    r, root, calls = _fetch(tmp_path, {"m/a.bin": (b"hello", _sha(b"hello"))},
                            existing={"m/a.bin": b"tampered"})
    assert r.returncode == 1 and calls == 0
    assert (root / "m/a.bin").read_bytes() == b"tampered"


def test_missing_lfs_pointer_fails_without_download(tmp_path):
    r, root, calls = _fetch(tmp_path, {"m/a.bin": (b"hello", None)})
    assert r.returncode == 1 and "NO-HASH" in r.stderr and calls == 0
    assert not (root / "m/a.bin").exists()


def test_manifest_urls_are_commit_pinned():
    rows = [line.split() for line in (REPO / "docker/comfyui/models.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    pinned = re.compile(r"^https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/")
    assert rows and all(len(r) == 2 and pinned.match(r[1]) for r in rows)
    names = {Path(r[0]).name for r in rows}
    assert set(cj.IMAGE_MODELS.values()) | set(cj.VIDEO_MODELS.values()) <= names


# ── comfy_job.py ──────────────────────────────────────────────────────────
def _links_resolve(wf):
    for node in wf.values():
        for v in node["inputs"].values():
            if isinstance(v, list):
                assert v[0] in wf, f"dangling link {v}"


def test_image_workflow_shape():
    wf = cj.image_workflow("a red fox", 7, prefix="p")
    _links_resolve(wf)
    ks = next(n for n in wf.values() if n["class_type"] == "KSampler")["inputs"]
    assert (ks["seed"], ks["cfg"], ks["steps"]) == (7, 1.0, 9)
    latent = next(n for n in wf.values() if n["class_type"] == "EmptySD3LatentImage")["inputs"]
    assert (latent["width"], latent["height"]) == (1024, 1024)


def test_video_workflow_splits_steps_between_experts():
    wf = cj.video_workflow("waves", 3, steps=6, frames=33)
    _links_resolve(wf)
    hi, lo = [n["inputs"] for n in wf.values() if n["class_type"] == "KSamplerAdvanced"]
    assert (hi["start_at_step"], hi["end_at_step"]) == (0, 3)
    assert lo["start_at_step"] == 3 and lo["add_noise"] == "disable"
    assert hi["return_with_leftover_noise"] == "enable"
    assert wf["11"]["inputs"]["length"] == 33


def test_output_files_and_errors():
    hist = {"p1": {"status": {"status_str": "success", "completed": True},
                   "outputs": {
                       "10": {"images": [
                           {"filename": "image_00001_.png", "subfolder": "", "type": "output"},
                           {"filename": "tmp.png", "subfolder": "", "type": "temp"}]},
                       "16": {"images": [{"filename": "v.mp4", "subfolder": "video",
                                          "type": "output"}],
                              "animated": [True]}}}}
    assert cj.output_files(hist, "p1", Path("/o")) == [Path("/o/image_00001_.png"),
                                                       Path("/o/video/v.mp4")]
    assert cj.job_finished(hist, "p1") and cj.job_error(hist, "p1") is None
    assert not cj.job_finished({}, "p1") and cj.output_files({}, "p1") == []
    err = {"p1": {"status": {"status_str": "error", "completed": False, "messages": [
        ["execution_start", {}],
        ["execution_error", {"node_type": "KSampler", "exception_message": "OOM\n"}]]}}}
    assert cj.job_finished(err, "p1") and cj.job_error(err, "p1") == "KSampler: OOM"


def test_gpu_warnings_name_heretic_and_ollama():
    notes = cj.gpu_warnings({1: ("/app/llama-server", 4800), 2: ("/usr/bin/ollama", 5000),
                             3: ("python", 100)})
    assert len(notes) == 2 and "parked" in notes[0] and "Klarheit" in notes[1]


def test_heretic_on_gpu_spots_llama_server_only():
    assert cj.heretic_on_gpu({1: ("/app/llama-server", 9842), 2: ("python", 192)})
    assert not cj.heretic_on_gpu({2: ("python", 192), 3: ("/usr/bin/ollama", 5000)})
    assert not cj.heretic_on_gpu({})


def test_main_parks_heretic_and_restarts_it_even_on_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(cj, "_http", lambda *a, **k: {})
    monkeypatch.setattr(cj, "wait_for_klarheit", lambda *a, **k: True)
    monkeypatch.setattr(cj, "gpu_apps", lambda: {1: ("/app/llama-server", 9842)})
    monkeypatch.setattr(cj, "_docker", lambda *a: calls.append(a) or True)

    def boom(*a):
        raise RuntimeError("job blew up")
    monkeypatch.setattr(cj, "run_job", boom)
    try:
        cj.main(["image", "x"])
    except RuntimeError:
        pass
    assert calls == [("stop", "llama-heretic"), ("start", "llama-heretic")]

    calls.clear()
    monkeypatch.setattr(cj, "run_job", lambda *a: 0)
    assert cj.main(["image", "x", "--keep-heretic"]) == 0 and calls == []


def test_next_trial_hourly_and_m12():
    from datetime import datetime as D
    assert cj.next_trial(D(2026, 10, 23, 15, 58)) == D(2026, 10, 23, 16, 5)
    assert cj.next_trial(D(2026, 10, 23, 16, 5)) == D(2026, 10, 23, 17, 5)
    assert cj.next_trial(D(2026, 10, 23, 10, 20)) == D(2026, 10, 23, 10, 35)
    assert cj.next_trial(D(2026, 10, 23, 23, 30)) == D(2026, 10, 24, 0, 5)


def test_klarheit_gate_by_kind():
    from datetime import datetime as D
    assert cj.klarheit_wait_reason("video", D(2026, 10, 23, 15, 20), True) == \
        "a Klarheit trial is running"
    # 15:58: video (12 min) would overlap 16:05; an image (3 min) would not
    assert "16:05" in cj.klarheit_wait_reason("video", D(2026, 10, 23, 15, 58), False)
    assert cj.klarheit_wait_reason("image", D(2026, 10, 23, 15, 58), False) is None
    assert cj.klarheit_wait_reason("video", D(2026, 10, 23, 15, 20), False) is None


def test_wait_for_klarheit_waits_then_gives_up():
    from datetime import datetime as D
    states = iter([True, True, False])
    slept = []
    assert cj.wait_for_klarheit("image", 600, sleep=slept.append,
                                clock=lambda: D(2026, 10, 23, 15, 20),
                                running=lambda: next(states))
    assert slept == [30, 30]
    assert not cj.wait_for_klarheit("image", 60, sleep=lambda s: None,
                                    clock=lambda: D(2026, 10, 23, 15, 20),
                                    running=lambda: True)


def test_klarheit_running_reads_systemctl():
    class R:
        def __init__(self, out): self.stdout = out
    assert cj.klarheit_running(run=lambda *a, **k: R("inactive\nactivating\n"))
    assert not cj.klarheit_running(run=lambda *a, **k: R("inactive\ninactive\n"))


def test_vram_sampler_stops_cleanly():
    # Regression: an Event named _stop shadowed Thread._stop and join() raised on Python 3.11.
    s = cj.VramSampler(None)
    s.start()
    s.stop()
    assert not s.is_alive()


def test_unreachable_server_exits_2_without_autostart(capsys):
    assert cj.main(["image", "x", "--url", "http://127.0.0.1:9", "--no-autostart"]) == 2
    assert "just comfy up -d" in capsys.readouterr().err


class _Run:
    def __init__(self, rc=0):
        self.rc, self.calls = rc, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return type("R", (), {"returncode": self.rc, "stdout": "", "stderr": "boom"})()


def test_start_comfy_waits_until_it_answers():
    run, answers = _Run(), iter([False, False, True])
    assert cj.start_comfy("u", run=run, up=lambda u: next(answers), sleep=lambda s: None)
    assert run.calls == [[str(cj.COMFY_SH), "up", "-d"]]


def test_start_comfy_reports_failure(capsys):
    assert not cj.start_comfy("u", run=_Run(rc=1), up=lambda u: True, sleep=lambda s: None)
    assert "could not start ComfyUI" in capsys.readouterr().err


def test_start_comfy_gives_up_if_never_ready(capsys):
    assert not cj.start_comfy("u", run=_Run(), up=lambda u: False, sleep=lambda s: None, wait=9)
    assert "didn't answer" in capsys.readouterr().err


def test_main_starts_and_stops_comfy_it_started(monkeypatch):
    events = []
    monkeypatch.setattr(cj, "comfy_up", lambda url: False)
    monkeypatch.setattr(cj, "start_comfy", lambda url: events.append("start") or True)
    monkeypatch.setattr(cj, "stop_comfy", lambda: events.append("stop"))
    monkeypatch.setattr(cj, "_with_gpu", lambda a, wf, seed: events.append("job") or 0)
    assert cj.main(["image", "x", "--ignore-klarheit"]) == 0
    assert events == ["start", "job", "stop"]


def test_main_leaves_running_comfy_alone(monkeypatch):
    events = []
    monkeypatch.setattr(cj, "comfy_up", lambda url: True)
    monkeypatch.setattr(cj, "start_comfy", lambda url: events.append("start") or True)
    monkeypatch.setattr(cj, "stop_comfy", lambda: events.append("stop"))
    monkeypatch.setattr(cj, "_with_gpu", lambda a, wf, seed: events.append("job") or 0)
    assert cj.main(["image", "x", "--ignore-klarheit"]) == 0
    assert events == ["job"]


def test_keep_up_skips_the_stop(monkeypatch):
    events = []
    monkeypatch.setattr(cj, "comfy_up", lambda url: False)
    monkeypatch.setattr(cj, "start_comfy", lambda url: True)
    monkeypatch.setattr(cj, "stop_comfy", lambda: events.append("stop"))
    monkeypatch.setattr(cj, "_with_gpu", lambda a, wf, seed: 0)
    assert cj.main(["image", "x", "--ignore-klarheit", "--keep-up"]) == 0
    assert events == []
