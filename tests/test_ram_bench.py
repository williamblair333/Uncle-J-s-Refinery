"""The RAM bench's two judgments: what counts as slow, and when Ollama may be stopped."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parent.parent / "scripts" / "ram_bench.py"
_spec = importlib.util.spec_from_file_location("ram_bench", _path)
ram_bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ram_bench)


def _stage(name, tps):
    return {"stage": name, "prompt_tps": tps, "gen_tps": 20, "wall_s": 5, "rss_gb": 18, "avail_gb": 20}


def test_stage_25_percent_below_baseline_is_slow():
    lines = ram_bench.summarize([_stage("baseline", 400), _stage("during", 300)])
    assert "SLOW" in lines[1]


def test_stage_near_baseline_is_not_slow():
    lines = ram_bench.summarize([_stage("baseline", 400), _stage("during", 350)])
    assert "SLOW" not in lines[1]


def test_failed_stage_is_reported_and_not_compared():
    lines = ram_bench.summarize([_stage("baseline", 400), {"stage": "during", "error": "timed out", "wall_s": 600}])
    assert lines[1].startswith("during") and "timed out" in lines[1]


def test_no_baseline_never_claims_slow():
    lines = ram_bench.summarize([{"stage": "baseline", "error": "refused", "wall_s": 1}, _stage("during", 1)])
    assert "SLOW" not in lines[1]


def test_every_klarheit_job_blocks_stopping_ollama():
    for job in ("klarheit-rv.service", "klarheit-cycle.service", "klarheit-m12.service"):
        assert ram_bench.running_jobs(is_running=lambda name: name == job) == [job]


def test_systemctl_error_counts_as_running(monkeypatch):
    class Proc:
        stdout = "unknown\n"

    monkeypatch.setattr(ram_bench.subprocess, "run", lambda *a, **kw: Proc())
    assert ram_bench.job_running("klarheit-rv.service")


def test_only_a_clear_stop_counts_as_stopped(monkeypatch):
    class Proc:
        stdout = "inactive\n"

    monkeypatch.setattr(ram_bench.subprocess, "run", lambda *a, **kw: Proc())
    assert not ram_bench.job_running("klarheit-rv.service")


def test_no_job_running_allows_stopping():
    assert ram_bench.running_jobs(is_running=lambda name: False) == []
