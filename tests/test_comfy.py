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
# Never wait on a real comfy_job run's lock from the tests.
import tempfile as _tempfile  # noqa: E402
cj.LOCK_PATH = Path(_tempfile.mkdtemp()) / "comfy_job.lock"
# Never stop or start real containers from the tests; the real functions are tested
# through these saved references with a fake `run`.
_real_park, _real_unpark = cj.park_containers, cj.unpark_containers
cj.park_containers = lambda *a, **k: []
cj.unpark_containers = lambda names, **k: True
_real_estimate = cj.park_estimate_gib
cj.park_estimate_gib = lambda *a, **k: 100.0

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_ram_gate(monkeypatch):
    """Never take a lease in the live store (~/.claude/state/ram-gate) from the tests."""
    monkeypatch.setenv("RAM_GATE_OFF", "1")


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
    assert set(cj.EDIT_MODELS.values()) <= names


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


def test_image_workflow_size_without_ref():
    wf = cj.image_workflow("x", 1, width=1344, height=768)
    assert (wf["7"]["inputs"]["width"], wf["7"]["inputs"]["height"]) == (1344, 768)
    assert wf["8"]["inputs"]["denoise"] == 1.0 and "11" not in wf


def test_image_workflow_ref_is_img2img():
    wf = cj.image_workflow("x", 1, ref_image="ref-abc.png", denoise=0.45)
    _links_resolve(wf)
    assert wf["11"] == {"class_type": "LoadImage", "inputs": {"image": "ref-abc.png"}}
    assert wf["12"]["class_type"] == "ImageScaleToTotalPixels"
    assert wf["12"]["inputs"]["resolution_steps"] == 16
    assert wf["7"]["class_type"] == "VAEEncode" and wf["7"]["inputs"]["pixels"] == ["12", 0]
    assert wf["8"]["inputs"]["denoise"] == 0.45
    sized = cj.image_workflow("x", 1, width=1024, height=576, ref_image="r.png")
    assert sized["12"]["class_type"] == "ImageScale"
    assert (sized["12"]["inputs"]["width"], sized["12"]["inputs"]["crop"]) == (1024, "center")


def test_bad_size_ref_or_denoise_exits_2_before_anything_runs(tmp_path, monkeypatch, capsys):
    def never(*a, **k):
        raise AssertionError("waited for Klarheit despite a bad argument")
    monkeypatch.setattr(cj, "wait_for_klarheit", never)
    assert cj.main(["image", "x", "--width", "1000"]) == 2
    assert cj.main(["image", "--seed", "-5", "--", "x"]) == 2
    assert cj.main(["image", "x", "--ref", str(tmp_path / "none.png")]) == 2
    other = tmp_path / "notes.key"
    other.write_text("not an image")
    assert cj.main(["image", "x", "--ref", str(other)]) == 2
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    assert cj.main(["image", "x", "--ref", str(img), "--denoise", "0"]) == 2
    assert cj.main(["video", "x", "--ref", str(img)]) == 2
    err = capsys.readouterr().err
    assert "multiple of 16" in err and "no such file" in err and "images only" in err


def test_ref_is_uploaded_once_comfy_is_up(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    events, got = [], {}
    monkeypatch.setattr(cj, "comfy_up", lambda url: True)
    monkeypatch.setattr(cj, "upload_image", lambda url, p: events.append(("up", p)) or "ref-1.png")
    monkeypatch.setattr(cj, "_with_gpu", lambda a, wf, seed: got.update(wf=wf) or 0)
    assert cj.main(["image", "x", "--ignore-klarheit", "--ref", str(img), "--seed", "3",
                    "--model", "z-image"]) == 0
    assert events == [("up", img)]
    assert got["wf"]["11"]["inputs"]["image"] == "ref-1.png"
    assert got["wf"]["8"]["inputs"]["denoise"] == cj.DEFAULT_DENOISE


def test_auto_model_edits_with_klein_from_several_refs(tmp_path, monkeypatch):
    a, b = tmp_path / "a.png", tmp_path / "b.jpg"
    a.write_bytes(b"1")
    b.write_bytes(b"2")
    got = {}
    monkeypatch.setattr(cj, "comfy_up", lambda url: True)
    monkeypatch.setattr(cj, "upload_image", lambda url, p: f"ref-{p.stem}.png")
    monkeypatch.setattr(cj, "_with_gpu", lambda a_, wf, seed: got.update(wf=wf) or 0)
    assert cj.main(["image", "--ignore-klarheit", "--ref", str(a), "--ref", str(b),
                    "--", "the two from image 1 and image 2 by a river"]) == 0
    wf = got["wf"]
    assert wf["1"]["inputs"]["unet_name"] == cj.EDIT_MODELS["unet"]
    assert [wf[k]["inputs"]["image"] for k in ("r0l", "r1l")] == ["ref-a.png", "ref-b.png"]


def test_edit_workflow_chains_references_like_the_template():
    wf = cj.edit_workflow("p", 9, ["a.png", "b.png"])
    _links_resolve(wf)
    assert wf["2"]["inputs"]["type"] == "flux2"
    assert wf["r1p"]["inputs"]["conditioning"] == ["r0p", 0]
    assert wf["r0n"]["inputs"]["conditioning"] == ["5", 0]
    g = wf["11"]["inputs"]
    assert (g["positive"], g["negative"], g["cfg"]) == (["r1p", 0], ["r1n", 0], 1.0)
    assert wf["8"]["inputs"]["steps"] == 4 and wf["9"]["inputs"]["noise_seed"] == 9
    assert wf["7"]["inputs"]["width"] == ["6", 0]          # first reference's size
    sized = cj.edit_workflow("p", 9, ["a.png"], width=1344, height=768)
    assert "6" not in sized and sized["8"]["inputs"]["width"] == 1344


def test_model_and_ref_count_rules(tmp_path, monkeypatch, capsys):
    def never(*a, **k):
        raise AssertionError("waited for Klarheit despite a bad argument")
    monkeypatch.setattr(cj, "wait_for_klarheit", never)
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    refs = [x for _ in range(2) for x in ("--ref", str(img))]
    assert cj.main(["image", "x", "--model", "z-image", *refs]) == 2
    assert cj.main(["image", "x", "--model", "klein"]) == 2
    assert cj.main(["image", "x", *(refs * 3)]) == 2
    err = capsys.readouterr().err
    assert "one --ref" in err and "from 1 to 4" in err
    assert cj.pick_model("auto", []) == "z-image" and cj.pick_model("auto", [img]) == "klein"


def test_upload_failure_still_stops_comfy_it_started(tmp_path, monkeypatch, capsys):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    events = []
    monkeypatch.setattr(cj, "comfy_up", lambda url: False)
    monkeypatch.setattr(cj, "start_comfy", lambda url: True)
    monkeypatch.setattr(cj, "stop_comfy", lambda: events.append("stop"))

    def refuse(url, p):
        raise cj.urllib.error.URLError("refused")
    monkeypatch.setattr(cj, "upload_image", refuse)
    assert cj.main(["image", "x", "--ignore-klarheit", "--ref", str(img)]) == 1
    assert events == ["stop"] and "could not upload" in capsys.readouterr().err


def test_upload_image_names_by_hash(tmp_path, monkeypatch):
    import json
    import re
    img = tmp_path / "Lineup.JPEG"
    img.write_bytes(b"abc")
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"name": sent["name"], "subfolder": "", "type": "input"}).encode()

    def opener(req, timeout):
        sent["body"], sent["ct"] = req.data, req.headers["Content-type"]
        sent["name"] = re.search(rb'filename="([^"]+)"', req.data).group(1).decode()
        return Resp()
    monkeypatch.setattr(cj.urllib.request, "urlopen", opener)
    assert cj.upload_image("http://u", img) == "ref-ba7816bf8f01.jpeg"
    assert b"\r\nabc\r\n" in sent["body"]
    assert sent["ct"].startswith("multipart/form-data; boundary=")


# --- Qwen-Image-Edit-2511 -------------------------------------------------------------

def _qwen_setup(monkeypatch, got, ram=30.0, waited=None, unloaded=None):
    """Never touches the real Ollama: unload_ollama is always replaced here."""
    monkeypatch.setattr(cj, "comfy_up", lambda url: True)
    monkeypatch.setattr(cj, "upload_image", lambda url, p: f"ref-{p.stem}.png")
    monkeypatch.setattr(cj, "ram_available_gib", ram if callable(ram) else (lambda: ram))
    monkeypatch.setattr(cj, "_with_gpu", lambda a_, wf, seed: got.update(wf=wf) or 0)
    events = waited if waited is not None else []

    def wait(kind, max_wait):
        events.append(kind)
        return True
    monkeypatch.setattr(cj, "wait_for_klarheit", wait)

    def unload():
        events.append("unload")
        return list(unloaded or [])
    monkeypatch.setattr(cj, "unload_ollama", unload)
    return events


def test_qwen_builds_its_graph_from_up_to_three_refs(tmp_path, monkeypatch):
    refs = []
    for n in "abc":
        p = tmp_path / f"{n}.png"
        p.write_bytes(b"1")
        refs += ["--ref", str(p)]
    got = {}
    _qwen_setup(monkeypatch, got)
    assert cj.main(["image", "--model", "qwen", *refs, "--", "Picture 1 and 2 by a river"]) == 0
    wf = got["wf"]
    _links_resolve(wf)
    assert wf["1"]["class_type"] == "UnetLoaderGGUF"
    assert wf["1"]["inputs"]["unet_name"] == cj.QWEN_MODELS["unet"]
    enc = wf["tp"]["inputs"]
    assert [wf[enc[f"image{i}"][0]]["inputs"]["image"][0] for i in (1, 2, 3)] == ["r0l", "r1l", "r2l"]
    assert wf["r0l"]["inputs"]["image"] == "ref-a.png"
    assert wf["8"]["inputs"]["positive"] == ["mp", 0] and wf["8"]["inputs"]["cfg"] == 1.0


def test_qwen_ref_count_rules(tmp_path, monkeypatch, capsys):
    img = tmp_path / "a.png"
    img.write_bytes(b"1")

    def never(*a, **k):
        raise AssertionError("waited for Klarheit despite a bad argument")
    monkeypatch.setattr(cj, "wait_for_klarheit", never)
    assert cj.main(["image", "x", "--model", "qwen"]) == 2
    assert cj.main(["image", "x", "--model", "qwen", *(["--ref", str(img)] * 4)]) == 2
    assert cj.main(["video", "x", "--model", "qwen", "--ref", str(img)]) == 2
    assert "from 1 to 3" in capsys.readouterr().err


def test_qwen_refuses_when_ram_is_low(tmp_path, monkeypatch, capsys):
    img = tmp_path / "a.png"
    img.write_bytes(b"1")
    got = {}
    _qwen_setup(monkeypatch, got, ram=12.5)
    assert cj.main(["image", "--model", "qwen", "--ref", str(img), "--", "x"]) == 1
    assert "wf" not in got
    assert "needs 20 GiB" in capsys.readouterr().err


def test_qwen_waits_for_klarheit_even_when_told_to_ignore_it(tmp_path, monkeypatch, capsys):
    img = tmp_path / "a.png"
    img.write_bytes(b"1")
    got, waited = {}, []
    _qwen_setup(monkeypatch, got, waited=waited)
    assert cj.main(["image", "--model", "qwen", "--ignore-klarheit", "--ref", str(img),
                    "--", "x"]) == 0
    assert waited == ["qwen"]  # 30 GiB free: nothing unloaded
    assert "always waits for Klarheit" in capsys.readouterr().err


def test_ram_gate_only_applies_to_listed_models(tmp_path):
    assert cj.ram_problem("klein", 1.0) is None
    assert cj.ram_problem("qwen", None) is None
    assert cj.ram_problem("qwen", 20.0) is None
    assert "12.0 GiB" in cj.ram_problem("qwen", 12.0)
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal: 48000000 kB\nMemAvailable: 20971520 kB\n")
    assert cj.ram_available_gib(mi) == 20.0
    assert cj.ram_available_gib(tmp_path / "missing") is None


def test_qwen_unloads_ollama_after_the_klarheit_wait_then_runs(tmp_path, monkeypatch, capsys):
    img = tmp_path / "a.png"
    img.write_bytes(b"1")
    got = {}
    readings = iter([13.0, 20.5, 20.5])
    events = _qwen_setup(monkeypatch, got, ram=lambda: next(readings), unloaded=["qwen3.5:9b"])
    assert cj.main(["image", "--model", "qwen", "--ref", str(img), "--", "x"]) == 0
    assert events == ["qwen", "unload"]  # never unloads before Klarheit is clear
    assert "wf" in got
    assert "unloaded Ollama's idle qwen3.5:9b" in capsys.readouterr().err


def test_free_ram_for_gives_up_when_unloading_is_not_enough():
    slept = []
    calls = []
    why = cj.free_ram_for("qwen", unload=lambda: calls.append(1) or ["m"],
                          available=lambda: 14.0, sleep=slept.append, wait=3)
    assert "needs 20 GiB" in why and "14.0 GiB" in why
    assert calls == [1] and slept == [1, 1, 1]


def test_free_ram_for_leaves_ollama_alone_when_ram_is_fine_or_ungated():
    def boom():
        raise AssertionError("unloaded Ollama without need")
    assert cj.free_ram_for("qwen", unload=boom, available=lambda: 25.0) is None
    assert cj.free_ram_for("klein", unload=boom, available=lambda: 1.0) is None


def test_unload_ollama_sets_keep_alive_zero_for_each_loaded_model():
    sent = []

    def http(url, payload=None, timeout=30):
        sent.append((url, payload))
        return {"models": [{"name": "qwen3.5:9b"}, {"name": "other"}]} if url.endswith("/api/ps") else {}
    assert cj.unload_ollama("http://o", http=http) == ["qwen3.5:9b", "other"]
    assert sent[1:] == [("http://o/api/generate", {"model": "qwen3.5:9b", "keep_alive": 0}),
                        ("http://o/api/generate", {"model": "other", "keep_alive": 0})]

    def down(url, payload=None, timeout=30):
        raise cj.urllib.error.URLError("refused")
    assert cj.unload_ollama("http://o", http=down) == []


def test_qwen_waits_longer_before_a_trial():
    import datetime as dt
    start = cj.next_trial(dt.datetime(2026, 11, 19, 12, 0))
    four_min_before = start - dt.timedelta(minutes=4)
    assert cj.klarheit_wait_reason("image", four_min_before, False) is None
    assert cj.klarheit_wait_reason("qwen", four_min_before, False)


# ── --region (crop, Qwen edit, paste back) ────────────────────────────────
def test_parse_region_and_its_errors():
    assert cj.parse_region("10, 20,300,400") == (10, 20, 300, 400)
    for bad in ("1,2,3", "a,b,c,d", "-1,0,100,100", "0,0,10,100"):
        try:
            cj.parse_region(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


def test_region_must_fit_the_picture():
    assert cj.region_problem((0, 0, 1536, 1024), (1536, 1024)) is None
    assert "past the picture's edge" in cj.region_problem((1400, 0, 200, 100), (1536, 1024))


def test_region_gen_size_keeps_aspect_at_about_a_megapixel():
    w, h = cj.region_gen_size(300, 450)
    assert w % 16 == 0 and h % 16 == 0
    assert abs(w / h - 300 / 450) < 0.03
    assert 0.9e6 < w * h < 1.1e6


class _DockerRun:
    def __init__(self, ps):
        self.calls, self.ps = [], ps

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = ""
        if cmd[:2] == ["docker", "ps"]:
            out = self.ps.get(cmd[3].rsplit("=", 1)[1], "")
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_park_stops_both_projects_and_unpark_starts_databases_first(tmp_path):
    marker = tmp_path / "comfy-parked.json"
    run = _DockerRun({"immich": "immich_server\nimmich_postgres\n",
                "claude-code-langfuse-template": "lf-web-1\nlf-clickhouse-1\n"})
    names = _real_park(run=run, marker=marker)
    assert names == ["immich_server", "immich_postgres", "lf-web-1", "lf-clickhouse-1"]
    assert run.calls[-1] == ["docker", "stop", *names]
    _real_unpark(names, run=run, marker=marker)
    assert run.calls[-1] == ["docker", "start", "immich_postgres", "lf-clickhouse-1",
                             "immich_server", "lf-web-1"]


def test_park_marker_written_before_stop(tmp_path):
    marker = tmp_path / "comfy-parked.json"
    checked = []

    class R(_DockerRun):
        def __call__(self, cmd, **kw):
            if cmd[:2] == ["docker", "stop"]:
                assert marker.exists()
                import json
                data = json.loads(marker.read_text())
                assert data["pid"] == os.getpid()
                assert data["names"] == ["immich_server"]
                assert "at" in data
                checked.append(True)
            return super().__call__(cmd, **kw)

    run = R({"immich": "immich_server\n"})
    names = _real_park(run=run, marker=marker)
    assert names == ["immich_server"]
    assert checked == [True]


def test_unpark_marker_removed_after_good_start_and_kept_after_failure(tmp_path):
    marker = tmp_path / "comfy-parked.json"
    names = ["immich_server"]

    # Failed start leaves marker
    marker.write_text('{"pid": 1, "names": ["immich_server"]}')
    run_fail = _Run(rc=1)
    assert not _real_unpark(names, run=run_fail, marker=marker)
    assert marker.exists()

    # Good start deletes marker
    run_ok = _Run(rc=0)
    assert _real_unpark(names, run=run_ok, marker=marker)
    assert not marker.exists()


def test_restore_stale_park_restarts_when_pid_dead(tmp_path, monkeypatch):
    import json
    marker = tmp_path / "comfy-parked.json"
    marker.write_text(json.dumps({"pid": 99999999, "names": ["immich_server", "lf-web-1"], "at": "..."}))
    run = _Run(rc=0)
    monkeypatch.setattr(cj, "unpark_containers", _real_unpark)
    restarted = cj.restore_stale_park(marker=marker, run=run, alive=lambda p: False)
    assert restarted == ["immich_server", "lf-web-1"]
    assert run.calls == [["docker", "start", "immich_server", "lf-web-1"]]
    assert not marker.exists()


def test_restore_stale_park_does_nothing_when_pid_alive(tmp_path, monkeypatch):
    import json
    marker = tmp_path / "comfy-parked.json"
    marker.write_text(json.dumps({"pid": os.getpid(), "names": ["immich_server"], "at": "..."}))
    run = _Run(rc=0)
    monkeypatch.setattr(cj, "unpark_containers", _real_unpark)
    restarted = cj.restore_stale_park(marker=marker, run=run, alive=lambda p: True)
    assert restarted == []
    assert run.calls == []
    assert marker.exists()


def test_restore_stale_park_does_nothing_when_no_marker(tmp_path, monkeypatch):
    marker = tmp_path / "nonexistent.json"
    run = _Run(rc=0)
    monkeypatch.setattr(cj, "unpark_containers", _real_unpark)
    assert cj.restore_stale_park(marker=marker, run=run) == []
    assert run.calls == []


def test_restore_stale_park_cleans_corrupt_marker(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "corrupt.json"
    marker.write_text("not json {{{")
    run = _Run(rc=0)
    monkeypatch.setattr(cj, "unpark_containers", _real_unpark)
    assert cj.restore_stale_park(marker=marker, run=run) == []
    assert run.calls == []
    assert not marker.exists()
    assert "corrupt or unreadable" in capsys.readouterr().err


def test_restore_parked_cli_flag(tmp_path, monkeypatch, capsys):
    # When no marker exists
    monkeypatch.setattr(cj, "restore_stale_park", lambda: [])
    assert cj.main(["--restore-parked"]) == 0
    assert capsys.readouterr().out.strip() == "nothing parked"

    # When stale marker exists and restarts
    monkeypatch.setattr(cj, "restore_stale_park", lambda: ["immich_server", "lf-web-1"])
    assert cj.main(["--restore-parked"]) == 0
    out = capsys.readouterr().out
    assert "immich_server" in out and "restarted" in out


def test_main_calls_restore_stale_park_before_ram_gate(monkeypatch, capsys):
    events = []
    monkeypatch.setattr(cj, "wait_for_klarheit", lambda *a, **k: True)
    monkeypatch.setattr(cj, "comfy_up", lambda *a, **k: True)
    monkeypatch.setattr(cj, "restore_stale_park", lambda: events.append("restore") or ["immich_server"])
    monkeypatch.setattr(cj, "free_ram_for", lambda *a, **k: events.append("ram_gate") or "short")
    assert cj.main(["image", "x", "--model", "z-image"]) == 1
    assert events == ["restore", "ram_gate"]
    assert "restarted immich_server" in capsys.readouterr().err


def test_park_with_nothing_running_stops_nothing():
    run = _DockerRun({})
    assert _real_park(run=run) == []
    assert not any(c[:2] == ["docker", "stop"] for c in run.calls)


def test_ram_gate_parks_only_when_unloading_ollama_is_not_enough():
    ram = iter([16.0, 16.0, 16.0, 23.0])
    parked: list[str] = []
    got = cj.free_ram_for("qwen", unload=lambda: [], available=lambda: next(ram),
                          sleep=lambda s: None, wait=2, park=lambda: ["immich_server"],
                          parked=parked)
    assert got is None and parked == ["immich_server"]
    # enough RAM at once: nothing parked
    parked = []
    assert cj.free_ram_for("qwen", unload=lambda: [], available=lambda: 25.0,
                           park=lambda: ["x"], parked=parked) is None and parked == []


def test_ram_gate_does_not_park_when_parking_cannot_reach_the_gate():
    parks = []
    got = cj.free_ram_for("qwen", unload=lambda: [], available=lambda: 13.5,
                          sleep=lambda s: None, wait=2, park=lambda: parks.append(1) or ["x"],
                          parked=[], estimate=lambda: 2.8)
    assert got and parks == []          # 13.5 + 2.8 < 20: nothing stopped, still refused


def test_park_estimate_sums_docker_stats():
    class R(_DockerRun):
        def __call__(self, cmd, **kw):
            if cmd[:2] == ["docker", "stats"]:
                return subprocess.CompletedProcess(
                    cmd, 0, "446.2MiB / 46.84GiB\n1.5GiB / 46.84GiB\n0B / 0B\n", "")
            return super().__call__(cmd, **kw)
    est = _real_estimate(run=R({"immich": "a\nb\n", "claude-code-langfuse-template": "c\n"}))
    assert abs(est - (446.2 / 1024 + 1.5)) < 1e-6
    assert cj._mem_gib("junk") == 0.0


def _gate_env(tmp_path, monkeypatch, avail_gib):
    monkeypatch.delenv("RAM_GATE_OFF", raising=False)
    monkeypatch.setenv("RAM_GATE_DIR", str(tmp_path / "store"))
    mem = tmp_path / "meminfo"
    mem.write_text(f"MemAvailable: {int(avail_gib * 1024 * 1024)} kB\n")
    monkeypatch.setenv("RAM_GATE_MEMINFO", str(mem))
    monkeypatch.setattr(cj, "wait_for_klarheit", lambda *a, **k: True)
    monkeypatch.setattr(cj, "free_ram_for", lambda *a, **k: None)
    monkeypatch.setattr(cj, "RAM_LEASE_GIB", {"z-image": 12})


def test_main_holds_a_ram_gate_lease_while_the_job_runs(tmp_path, monkeypatch):
    _gate_env(tmp_path, monkeypatch, 25)
    seen = []
    monkeypatch.setattr(cj, "_start_and_run",
                        lambda *a: seen.append(cj.ram_gate.status()["leases"]) or 0)
    assert cj.main(["image", "x", "--model", "z-image"]) == 0
    assert [x["label"] for x in seen[0]] == ["comfy_job z-image"] and seen[0][0]["gib"] == 12
    assert cj.ram_gate.status()["leases"] == []              # released at the end


def test_main_refused_by_the_ram_gate_does_not_start(tmp_path, monkeypatch, capsys):
    _gate_env(tmp_path, monkeypatch, 15)                    # 15 - 12 < 6
    monkeypatch.setattr(cj, "_start_and_run", lambda *a: pytest.fail("must not start"))
    assert cj.main(["image", "x", "--model", "z-image"]) == 1
    assert "ram gate refused the z-image job" in capsys.readouterr().err


def test_main_restarts_parked_containers_even_when_the_gate_still_fails(monkeypatch):
    restarted = []
    monkeypatch.setattr(cj, "wait_for_klarheit", lambda kind, max_wait: True)
    monkeypatch.setattr(cj, "comfy_up", lambda url: True)
    monkeypatch.setattr(cj, "free_ram_for",
                        lambda model, parked: parked.append("immich_server") or "still short")
    monkeypatch.setattr(cj, "unpark_containers", lambda names: restarted.extend(names))
    assert cj.main(["image", "x", "--model", "z-image"]) == 1
    assert restarted == ["immich_server"]


def test_second_run_waits_for_the_lock(tmp_path):
    lock = tmp_path / "l"
    held = cj.hold_lock(lock)
    child = subprocess.run(
        ["/usr/bin/python3", "-c",
         "import fcntl,sys; f=open(sys.argv[1],'a')\n"
         "try:\n fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB); print('GOT')\n"
         "except BlockingIOError: print('BLOCKED')", str(lock)],
        capture_output=True, text=True, timeout=30)
    assert child.stdout.strip() == "BLOCKED"
    held.close()
    again = cj.hold_lock(lock)
    again.close()


def test_region_flags_need_region():
    assert cj.main(["image", "x", "--feather", "8"]) == 2


# Pillow is in the system python3 (which `just image` runs) but not in .venv, so the pixel
# test runs there: crop → fake job → paste, and every pixel outside the box must be equal.
_REGION_SCRIPT = r'''
import importlib.util, sys
from pathlib import Path
from PIL import Image
spec = importlib.util.spec_from_file_location("cj", sys.argv[1])
cj = importlib.util.module_from_spec(spec); spec.loader.exec_module(cj)
tmp = Path(sys.argv[2])
cj.LOCK_PATH = tmp / "comfy_job.lock"
scene = tmp / "scene.png"
im = Image.new("RGB", (640, 480))
im.putdata([((x * 7) % 256, (y * 3) % 256, (x + y) % 256) for y in range(480) for x in range(640)])
im.save(scene)
face = tmp / "face.png"; Image.new("RGB", (64, 64), (9, 9, 9)).save(face)
got = {}
cj.comfy_up = lambda url: True
cj.ram_available_gib = lambda: 30.0
cj.unload_ollama = lambda: []
def wait(kind, max_wait):
    got["waited"] = kind
    return True
cj.wait_for_klarheit = wait
def upload(url, p):
    got.setdefault("uploaded", []).append(Image.open(p).size)
    return p.name
cj.upload_image = upload
def fake_gpu(args, wf, seed):
    got["latent"] = (wf["7"]["inputs"]["width"], wf["7"]["inputs"]["height"])
    patch = tmp / "patch.png"
    Image.new("RGB", got["latent"], (255, 0, 0)).save(patch)
    args.outputs = [patch]
    return 0
cj._with_gpu = fake_gpu
out = tmp / "fixed.png"
rc = cj.main(["image", "fix the face", "--ref", str(scene), "--ref", str(face),
              "--region", "100,50,200,160", "--out", str(out), "--seed", "1"])
assert rc == 0, rc
assert got["waited"] == "qwen"
assert got["uploaded"] == [(200, 160), (64, 64)], got   # the crop, then the face ref
assert abs(got["latent"][0] / got["latent"][1] - 200 / 160) < 0.05
assert cj.outside_unchanged(scene, out, (100, 50, 200, 160))
res = Image.open(out)
assert res.getpixel((200, 130)) == (255, 0, 0)            # centre of the box: replaced
assert res.getpixel((100, 50)) == im.getpixel((100, 50))  # box corner: faded to original
# never overwrites, refuses a box off the picture, catches a change outside the box
assert cj.main(["image", "again", "--ref", str(scene), "--region", "100,50,200,160",
                "--out", str(out), "--seed", "2"]) == 2
assert cj.main(["image", "x", "--ref", str(scene), "--region", "600,0,100,100",
                "--out", str(tmp / "o2.png")]) == 2
other = tmp / "other.png"; Image.new("RGB", (640, 480)).save(other)
assert not cj.outside_unchanged(scene, other, (100, 50, 200, 160))
print("REGION-OK")
'''


def test_region_crop_and_paste_leave_outside_pixels_identical(tmp_path):
    py = "/usr/bin/python3"
    probe = subprocess.run([py, "-c", "import PIL"], capture_output=True)
    assert probe.returncode == 0, "system python3 lacks Pillow, which `just image --region` needs"
    script = tmp_path / "region_check.py"
    script.write_text(_REGION_SCRIPT)
    r = subprocess.run([py, "-I", str(script), str(REPO / "scripts" / "comfy_job.py"),
                        str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert "REGION-OK" in r.stdout, r.stdout + r.stderr


# --- RAM guard (2026-11-19: the kernel OOM-killed Chrome at the end of a Qwen job) ---

def test_ram_guard_trips_only_below_the_floor():
    assert cj.ram_guard_tripped(3.9)
    assert not cj.ram_guard_tripped(4.0)
    assert not cj.ram_guard_tripped(None)  # unreadable meminfo never kills a job


def test_watch_ram_returns_the_low_reading_mid_wait():
    readings = iter([10.0, 8.0, 3.5, 20.0])
    sleeps = []
    low = cj.watch_ram(2, available=lambda: next(readings), sleep=sleeps.append, poll=0.5)
    assert low == 3.5
    assert sleeps == [0.5, 0.5]


def test_watch_ram_waits_the_full_time_when_ram_is_fine():
    sleeps = []
    assert cj.watch_ram(2, available=lambda: 20.0, sleep=sleeps.append, poll=0.5) is None
    assert sum(sleeps) == 2


def test_run_job_kills_comfyui_when_the_guard_trips(monkeypatch, capsys):
    import argparse

    class Sampler:
        peak_proc = peak_total = 0
        def __init__(self, pid): pass
        def start(self): pass
        def stop(self): pass

    calls = []
    monkeypatch.setattr(cj, "VramSampler", Sampler)
    monkeypatch.setattr(cj, "container_pid", lambda: None)
    monkeypatch.setattr(cj, "_http",
                        lambda url, payload=None: {"prompt_id": "p1"} if payload else {})
    monkeypatch.setattr(cj, "watch_ram", lambda s: 2.5)
    monkeypatch.setattr(cj, "_docker", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(cj, "free_vram", lambda url: calls.append(("free",)) or True)
    args = argparse.Namespace(url="http://x", kind="image", timeout=60, keep_loaded=False)
    assert cj.run_job(args, {}, 7) == 1
    assert calls == [("kill", "comfyui")]
    assert "free RAM fell to 2.5 GiB" in capsys.readouterr().err
