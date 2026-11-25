"""scripts/gpu_watch.py: GPU containers that lost the GPU, and models running on CPU.

On 2026-11-24 the host Ollama lost the GPU (NVIDIA toolkit + systemctl daemon-reload),
ran a 9B on CPU beside Heretic and a VM, and dma64 froze. These tests drive the checker
with a fake command runner, so no docker or GPU is needed.
"""
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gpu_watch.py"
spec = importlib.util.spec_from_file_location("gpu_watch", SCRIPT)
gw = importlib.util.module_from_spec(spec)
sys.modules["gpu_watch"] = gw  # dataclasses resolve the module by name
spec.loader.exec_module(gw)

GPU_LINE = "GPU 0: NVIDIA GeForce RTX 3060 (UUID: GPU-x)"
CDI = json.dumps([{"Driver": "cdi", "DeviceIDs": ["nvidia.com/gpu=all"], "Capabilities": [["gpu"]]}])
OLD = json.dumps([{"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}])
def ollama_table(*rows):
    """Lay rows out the way `ollama ps` does: each column padded to its widest cell + 4."""
    table = [("NAME", "ID", "SIZE", "PROCESSOR", "CONTEXT", "UNTIL"), *rows]
    widths = [max(len(r[i]) for r in table) + 4 for i in range(5)]
    return "".join("".join(c.ljust(w) for c, w in zip(r[:5], widths)) + r[5] + "\n" for r in table)


ROW = ("qwen3.5:9b", "6488c96fa5fa", "6.0 GB", "100% GPU", "16384", "9 minutes from now")
OLLAMA_GPU = ollama_table(ROW)
OLLAMA_CPU = ollama_table(ROW[:3] + ("100% CPU",) + ROW[4:])
OLLAMA_MIXED = ollama_table(ROW[:3] + ("37%/63% CPU/GPU",) + ROW[4:])
OLLAMA_EMPTY = ollama_table()


NO_BINARY = (127, "[Errno 2] No such file or directory: 'nvidia-smi'")  # run_cmd's OSError


def runner(containers, host_gpu=True, ollama_ps=OLLAMA_EMPTY, docker_up=True, host_smi=None,
           ollama_rc=0):
    """containers: {name: (device_requests_json, nvidia_smi_output_or_None)}."""
    def run(cmd):
        if cmd[:2] == ["nvidia-smi", "-L"]:
            if host_smi is not None:
                return host_smi
            return (0, GPU_LINE) if host_gpu else NO_BINARY
        if cmd[:2] == ["docker", "ps"]:
            return (0, "\n".join(containers)) if docker_up else (1, "Cannot connect")
        if cmd[:2] == ["docker", "inspect"]:
            return 0, containers[cmd[-1]][0]
        if cmd[:2] == ["docker", "exec"] and cmd[3:5] == ["nvidia-smi", "-L"]:
            out = containers[cmd[2]][1]
            return (0, out) if out is not None else (255, "Failed to initialize NVML: Unknown Error")
        if cmd[:2] == ["docker", "exec"] and cmd[3:5] == ["ollama", "ps"]:
            return ollama_rc, ollama_ps
        raise AssertionError(f"unexpected command {cmd}")
    return run


def test_healthy_cdi_containers_pass():
    r = gw.check(runner({"ollama": (CDI, GPU_LINE), "llama-heretic": (CDI, GPU_LINE),
                         "immich_server": ("[]", None)}, ollama_ps=OLLAMA_GPU))
    assert r.problems == [] and r.notes == [] and r.state == "ok"


def test_container_that_lost_the_gpu_is_a_problem():
    r = gw.check(runner({"ollama": (CDI, None)}))
    assert r.problems == ["ollama can't see the GPU (Failed to initialize NVML: Unknown Error)"]


def test_model_on_cpu_is_a_problem():
    r = gw.check(runner({"ollama": (CDI, GPU_LINE)}, ollama_ps=OLLAMA_CPU))
    assert r.problems == ["ollama runs qwen3.5:9b on 100% CPU (host RAM, not VRAM)"]


def test_model_split_across_cpu_and_gpu_is_a_problem():
    r = gw.check(runner({"ollama": (CDI, GPU_LINE)}, ollama_ps=OLLAMA_MIXED))
    assert r.problems == ["ollama runs qwen3.5:9b on 37%/63% CPU/GPU (host RAM, not VRAM)"]


def test_model_sized_in_mb_on_cpu_is_still_caught():
    ps = ollama_table(("qwen3:0.6b", "7df6b6e09427", "523 MB", "100% CPU", "4096", "4 minutes from now"))
    r = gw.check(runner({"ollama": (CDI, GPU_LINE)}, ollama_ps=ps))
    assert r.problems == ["ollama runs qwen3:0.6b on 100% CPU (host RAM, not VRAM)"]


def test_old_style_gpu_request_is_a_note_not_a_problem():
    r = gw.check(runner({"llama-heretic": (OLD, GPU_LINE)}))
    assert r.problems == []
    assert r.notes == ["llama-heretic uses driver: nvidia; a daemon-reload can drop its GPU (use CDI)"]


def test_containers_without_gpu_are_not_probed():
    r = gw.check(runner({"immich_server": ("[]", None)}))  # exec would fail if probed
    assert r.problems == [] and r.state == "ok"


def test_host_without_gpu_is_not_applicable():
    r = gw.check(runner({}, host_gpu=False))
    assert r.state == "na" and r.problems == []


def test_docker_down_is_unknown_not_ok():
    r = gw.check(runner({}, docker_up=False))
    assert r.state == "unknown"


def test_host_driver_failing_is_unknown_not_no_gpu():
    r = gw.check(runner({}, host_smi=(9, "Failed to initialize NVML: Unknown Error")))
    assert r.state == "unknown"


def test_ollama_ps_error_is_unknown_not_clean():
    r = gw.check(runner({"ollama": (CDI, GPU_LINE)}, ollama_ps="Error: server busy", ollama_rc=1))
    assert r.state == "unknown" and r.problems == []


def _sender(sent, ok=True):
    def send(text):
        sent.append(text)
        return ok
    return send


def test_alert_only_on_change_and_on_recovery(tmp_path):
    state = tmp_path / "gpu-watch.json"
    sent = []
    bad = gw.Result(state="problem", problems=["ollama can't see the GPU (x)"], restart=["ollama"])
    good = gw.Result(state="ok")
    gw.alert_on_change(bad, state, _sender(sent))
    gw.alert_on_change(bad, state, _sender(sent))       # same problem: no repeat
    gw.alert_on_change(good, state, _sender(sent))      # recovery: one message
    gw.alert_on_change(good, state, _sender(sent))
    assert len(sent) == 2
    assert "ollama can't see the GPU" in sent[0] and "docker restart ollama" in sent[0]
    assert "back on the GPU" in sent[1]


def test_failed_send_is_retried_next_run(tmp_path):
    state = tmp_path / "gpu-watch.json"
    sent = []
    bad = gw.Result(state="problem", problems=["ollama runs m on 100% CPU (host RAM, not VRAM)"])
    gw.alert_on_change(bad, state, _sender(sent, ok=False))   # Telegram down
    gw.alert_on_change(bad, state, _sender(sent, ok=True))    # next run: sent again
    gw.alert_on_change(bad, state, _sender(sent, ok=True))    # now recorded: quiet
    assert len(sent) == 2


def test_cpu_message_has_no_html_tags():
    # lib/notify.sh sends parse_mode HTML; a bare <word> makes Telegram reject the message.
    msg = gw._message(gw.Result(state="problem", problems=["ollama runs m on 100% CPU (x)"]))
    assert "<" not in msg and ">" not in msg
