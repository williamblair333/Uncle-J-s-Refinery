"""scripts/ram_gate.py: leases, the floor, VM detection and sizing, and the hook wrapper."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ram_gate", ROOT / "scripts" / "ram_gate.py")
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="flock + /proc are Linux-only")


@pytest.fixture
def env(tmp_path, monkeypatch):
    mem = tmp_path / "meminfo"

    def set_avail(gib: float):
        mem.write_text(f"MemTotal: 48000000 kB\nMemAvailable: {int(gib * 1024 * 1024)} kB\n")

    set_avail(20)
    monkeypatch.setenv("RAM_GATE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("RAM_GATE_MEMINFO", str(mem))
    monkeypatch.delenv("RAM_GATE_FLOOR_GIB", raising=False)
    monkeypatch.delenv("RAM_GATE_OFF", raising=False)
    return set_avail


# ── leases ──────────────────────────────────────────────────────────────────

def test_grant_then_lease_counts_against_next(env):
    ok, lid = rg.acquire(8, "a", 600)
    assert ok and len(lid) == 12
    ok2, why = rg.acquire(8, "b", 600)          # 20 - 8 - 8 = 4 < 6
    assert not ok2
    assert "already leased: a 8.0 of 8 GiB" in why and "under the 6 GiB floor" in why


def test_floor_exact_edge_grants(env):
    ok, _ = rg.acquire(14, "x", 600)            # 20 - 14 = 6, not under 6
    assert ok


def test_release_frees(env):
    _, lid = rg.acquire(8, "a", 600)
    assert rg.release(lid)
    assert rg.acquire(8, "b", 600)[0]
    assert not rg.release("nope")


def test_expired_lease_ignored(env):
    rg.acquire(10, "old", 60, now=1000.0)
    assert rg.acquire(10, "new", 60, now=2000.0)[0]
    assert rg.acquire(10, "also", 60, now=1010.0)[0] is False   # "old" still holds ~8.3


def test_lease_context_holds_then_releases(env):
    with rg.lease(8, "load", 600) as lid:
        assert [x["id"] for x in rg.status()["leases"]] == [lid]
    assert rg.status()["leases"] == []


def test_lease_context_releases_when_the_body_raises(env):
    with pytest.raises(RuntimeError):
        with rg.lease(8, "load", 600):
            raise RuntimeError("load failed")
    assert rg.status()["leases"] == []


def test_lease_context_refuses_before_the_body(env):
    env(10)
    with pytest.raises(rg.Refused, match="under the 6 GiB floor"):
        with rg.lease(8, "load", 600):
            pytest.fail("body must not run")


def test_lease_context_off_or_zero_skips(env, monkeypatch):
    env(1)
    with rg.lease(0, "nothing coming") as lid:
        assert lid is None
    monkeypatch.setenv("RAM_GATE_OFF", "1")
    with rg.lease(8, "off") as lid:
        assert lid is None
    assert rg.status()["leases"] == []


def test_lease_context_fails_open_when_the_gate_breaks(env, monkeypatch):
    def broken(*a, **k):
        raise ImportError("No module named 'fcntl'")   # what Windows does
    monkeypatch.setattr(rg, "acquire", broken)
    with rg.lease(8, "win") as lid:
        assert lid.startswith("unmeasured")


def test_lease_context_busy_lock_is_a_refusal(env, monkeypatch):
    def busy(*a, **k):
        raise TimeoutError("ram-gate lock busy for 10 s")
    monkeypatch.setattr(rg, "acquire", busy)
    with pytest.raises(rg.Refused, match="busy"):
        with rg.lease(8, "x"):
            pass


def test_lease_shrinks_over_ttl(env):
    env(20)
    rg.acquire(8, "vm", 600, now=1000.0)
    assert rg.acquire(8, "b", 600, now=1010.0)[0] is False       # vm holds ~7.9: 20-7.9-8 < 6
    assert rg.acquire(8, "c", 600, now=1450.0)[0]                # vm holds 2: 20-2-8 = 10


def test_same_label_replaces_not_stacks(env):
    env(20)
    for _ in range(3):
        assert rg.acquire(8, "VM: virsh start t", 600)[0]
    assert len(rg.status()["leases"]) == 1


def test_lock_timeout(env, monkeypatch):
    import fcntl
    monkeypatch.setattr(rg, "LOCK_WAIT", 0.2)
    d = Path(os.environ["RAM_GATE_DIR"])
    d.mkdir(parents=True)
    with open(d / "lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        with pytest.raises(TimeoutError):
            rg.acquire(1, "x", 60)


def test_low_memory_refuses_and_names_top_users(env):
    env(5)
    ok, why = rg.acquire(1, "tiny", 600)
    assert not ok and "MemAvailable is 5.0 GiB" in why and "biggest:" in why


def test_floor_env(env, monkeypatch):
    monkeypatch.setenv("RAM_GATE_FLOOR_GIB", "1")
    assert rg.acquire(18, "x", 600)[0]


def test_unreadable_meminfo_grants_without_lease(env, monkeypatch, tmp_path):
    monkeypatch.setenv("RAM_GATE_MEMINFO", str(tmp_path / "missing"))
    ok, msg = rg.acquire(100, "x", 600)
    assert ok and msg.startswith("unmeasured")
    assert rg.status()["leases"] == []


def test_corrupt_store_reads_as_empty(env):
    rg.acquire(1, "a", 600)
    (Path(os.environ["RAM_GATE_DIR"]) / "leases.json").write_text("{not json")
    assert rg.status()["leases"] == []
    assert rg.acquire(8, "b", 600)[0]


def test_concurrent_acquires_never_overcommit(env):
    env(20)                                      # room for exactly one 8 GiB lease above 6
    results = []

    def go(i):
        results.append(rg.acquire(8, f"t{i}", 600)[0])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count(True) == 1


def test_cli_exit_codes(env):
    py = [sys.executable, str(ROOT / "scripts" / "ram_gate.py")]
    r = subprocess.run(py + ["acquire", "--gib", "8", "--label", "cli"], capture_output=True, text=True)
    assert r.returncode == 0 and len(r.stdout.strip()) == 12
    r = subprocess.run(py + ["acquire", "--gib", "8", "--label", "cli2"], capture_output=True, text=True)
    assert r.returncode == 1 and r.stderr.startswith("ram-gate: refused")
    r = subprocess.run(py + ["acquire", "--gib", "0", "--label", "z"], capture_output=True, text=True)
    assert r.returncode == 2
    s = json.loads(subprocess.run(py + ["status"], capture_output=True, text=True).stdout)
    assert [x["label"] for x in s["leases"]] == ["cli"]


# ── which commands start a VM here ──────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "virsh start mtw2-test",
    "sudo virsh -c qemu:///system start mtw2-test",
    "cd /x && virsh create dom.xml",
    "virt-install --name t --memory 4096 --disk none",
    "LIBVIRT_DEFAULT_URI=qemu:///system virsh start t",
    "timeout 30 virsh start t",
    "qemu-system-x86_64 -m 2G -hda x.img",
    "nohup /usr/bin/qemu-system-aarch64 -m 512 &",
    "echo hi\nvirsh start t",
    "sudo -n virsh start x",
    "sudo -u root -E virsh start x",
    "for v in a b; do virsh start $v; done",
    "if true; then virsh start x; fi",
    "echo a#b; virsh start x",
    "virsh -d 4 start x",
    "virsh -c qemu:///system start x",
    "printf 'a\\nb\\n' | xargs -n1 virsh start",
    "cat <<EOF > f\nhi\nEOF\nvirsh start x",
])
def test_detects_vm_start(cmd):
    assert rg.vm_starts(cmd)


@pytest.mark.parametrize("cmd", [
    "ssh tc-vmh-03 virsh start t",
    "ssh tc-vmh-03 'virsh start t'",
    'git commit -m "gate virsh start and virt-install; qemu-system-x86_64 too"',
    "grep -n virt-install scripts/x.py",
    "echo virsh start t",
    "virsh list --all",
    "virsh shutdown t",
    "man qemu-system-x86_64",
    "cat <<'EOF' > notes.md\nwe ran it\nEOF",
    "printf 'unbalanced",
    "x <<E\nvirsh start vm1\nE",
    "cat > runbook.sh <<'EOF'\nvirsh start vm1\nEOF",
    "virsh -c qemu+ssh://h/system start x",
    "virsh --connect=qemu+ssh://h/system start x",
    "LIBVIRT_DEFAULT_URI=qemu+ssh://h/system virsh start x",
    "virt-install --connect qemu+ssh://h/system --memory 4096",
    "virt-install --print-xml --memory 4096",
    "virt-install --dry-run --memory 4096",
    "virsh start --help",
    "qemu-system-x86_64 --version",
    "qemu-system-x86_64 -M help",
])
def test_ignores_non_starts(cmd):
    assert rg.vm_starts(cmd) == []


# ── sizing ──────────────────────────────────────────────────────────────────

def _words(cmd):
    return rg.vm_starts(cmd)[0]


def test_size_virt_install():
    assert rg.vm_gib(_words("virt-install --name t --memory 6144")) == (6.0, "virt-install --memory")
    assert rg.vm_gib(_words("virt-install --memory=memory=2048,maxmemory=4096"))[0] == 2.0
    assert rg.vm_gib(_words("virt-install --ram 1024"))[0] == 1.0


def test_size_qemu():
    assert rg.vm_gib(_words("qemu-system-x86_64 -m 2G"))[0] == 2.0
    assert rg.vm_gib(_words("qemu-system-x86_64 -m 1024"))[0] == 1.0
    assert rg.vm_gib(_words("qemu-system-x86_64 -m size=512M,slots=2"))[0] == 0.5
    assert rg.vm_gib(_words("qemu-system-x86_64 -hda x"))[1] == "qemu default -m"


def test_size_virsh_dominfo_passes_connect():
    seen = {}

    def fake(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="Name: t\nMax memory:     6291456 KiB\n")

    g, src = rg.vm_gib(_words("virsh -c qemu:///system start t"), run=fake)
    assert (g, src) == (6.0, "virsh dominfo")
    assert seen["argv"] == ["virsh", "-c", "qemu:///system", "dominfo", "t"]


def test_running_domain_is_not_gated(env):
    env(1)

    def running(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout="State:          running\nMax memory:     16777216 KiB\n")

    assert rg.vm_gib(_words("virsh start t"), run=running) == (0.0, "already running")
    assert rg.hook({"tool_name": "Bash", "tool_input": {"command": "virsh start t"}}, run=running) is None
    assert rg.status()["leases"] == []


def test_size_virsh_failure_assumes_default():
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)

    assert rg.vm_gib(_words("virsh start t"), run=boom) == (rg.DEFAULT_VM_GIB, "assumed")


def test_size_virsh_create_xml(tmp_path):
    x = tmp_path / "d.xml"
    x.write_text("<domain><memory unit='GiB'>3</memory></domain>")
    assert rg.vm_gib(_words(f"virsh create {x}")) == (3.0, "domain XML")


# ── hook ────────────────────────────────────────────────────────────────────

def _assume(argv, **kw):
    return subprocess.CompletedProcess(argv, 1, stdout="")


def test_hook_refuses_and_skip_marker(env):
    env(10)
    data = {"tool_name": "Bash", "tool_input": {"command": "virsh start t"}}
    msg = rg.hook(data, run=_assume)            # assumed 8 GiB: 10 - 8 = 2 < 6
    assert msg.startswith("ram-gate: VM start refused") and "8 GiB (assumed)" in msg
    data["tool_input"]["command"] = "virsh start t  # ram-gate: ok tiny test domain"
    assert rg.hook(data, run=_assume) is None


def test_hook_grant_leaves_lease_for_others(env):
    env(16)
    assert rg.hook({"tool_name": "Bash", "tool_input": {"command": "virt-install --memory 4096"}}) is None
    ok, why = rg.acquire(8, "heretic", 600)     # 16 - 4 - 8 = 4 < 6
    assert not ok and "VM: virt-install" in why


def test_hook_ignores_other_tools(env):
    env(1)
    assert rg.hook({"tool_name": "Read", "tool_input": {"command": "virsh start t"}}) is None


def _run_wrapper(cmd, tmp_path, extra_env):
    payload = json.dumps({"tool_name": "Bash", "session_id": "s1", "tool_input": {"command": cmd}})
    e = {**os.environ, **extra_env, "RAM_GATE_LOG": str(tmp_path / "blocks.log")}
    return subprocess.run(["bash", str(ROOT / "hooks" / "discipline" / "ram-gate.sh")],
                          input=payload, capture_output=True, text=True, env=e)


def test_wrapper_blocks_with_exit_2_and_logs(env, tmp_path):
    env(3)
    r = _run_wrapper("virt-install --memory 4096", tmp_path, {})
    assert r.returncode == 2 and "ram-gate: VM start refused" in r.stderr
    assert "BLOCKED ram-gate cmd=virt-install --memory 4096 session=s1" in (tmp_path / "blocks.log").read_text()


def test_wrapper_passes_plain_commands(env, tmp_path):
    env(1)
    assert _run_wrapper("ls -la", tmp_path, {}).returncode == 0
    assert not (tmp_path / "blocks.log").exists()


def test_wrapper_fails_open_when_judge_crashes(env, tmp_path):
    env(1)
    # an unusable store dir makes the judge raise: a crash must not block
    bad = tmp_path / "file-not-dir"
    bad.write_text("x")
    r = _run_wrapper("virt-install --memory 4096", tmp_path, {"RAM_GATE_DIR": str(bad / "sub")})
    assert r.returncode == 0
