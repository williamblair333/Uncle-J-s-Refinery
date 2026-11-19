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
