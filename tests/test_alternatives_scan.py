"""features/prompt-triggers: alternatives_scan.py (registry) + alternatives_gate.py (download gate)
+ the router's alternatives-scan route."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "features" / "prompt-triggers"
sys.path.insert(0, str(HERE))
import alternatives_gate as gate  # noqa: E402
import alternatives_scan as scan  # noqa: E402
import skill_router as sr  # noqa: E402

REPORT = """# Alternatives: Strata

| name | what | stars | fits |
|---|---|---|---|
| Niko1221/Strata | engine | 38899 | yes |
| freriadoc/Avalon | llama.cpp fork | 246 | maybe |
| jesdga95/basalt | Blackwell only | 485 | no |

## Verdict
Test Avalon first.
"""


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("ALT_SCAN_STATE", str(tmp_path / "state"))
    report = tmp_path / "report.md"
    report.write_text(REPORT)
    return tmp_path, report


def record(report, covers="Avalon,freriadoc/Avalon,Niko1221/Strata"):
    return scan.main(["record", "--subject", "Strata", "--category", "Qwen3.8 local engine",
                      "--covers", covers, "--report", str(report)])


def run_gate(command, env=None):
    event = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": command}}
    r = subprocess.run([sys.executable, str(HERE / "alternatives_gate.py")], input=json.dumps(event),
                       capture_output=True, text=True, timeout=20, env={**os.environ, **(env or {})})
    assert r.returncode == 0
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else "allow"


# --- registry -----------------------------------------------------------------------------

def test_record_then_covers_the_candidates_downloads(state):
    _, report = state
    assert record(report) == 0
    scans = scan.recent_scans()
    assert scan.covering_scan("https://github.com/freriadoc/Avalon", scans)
    assert scan.covering_scan("freriadoc/Qwen3.8-Flash-Next-Avalon-GGUF", scans)
    assert scan.covering_scan("https://github.com/Niko1221/Strata.git", scans)
    assert not scan.covering_scan("https://github.com/ggml-org/llama.cpp", scans)


def test_record_refuses_thin_reports_and_generic_names(state):
    tmp, report = state
    thin = tmp / "thin.md"
    thin.write_text("| a | b |\n|---|---|\n| x | y |\n\n## Verdict\nok\n")
    assert scan.main(["record", "--subject", "Strata", "--category", "c", "--covers", "Avalon",
                      "--report", str(thin)]) == 2
    no_verdict = tmp / "nov.md"
    no_verdict.write_text(REPORT.replace("## Verdict", "## Notes"))
    assert scan.main(["record", "--subject", "Strata", "--category", "c", "--covers", "Avalon",
                      "--report", str(no_verdict)]) == 2
    assert scan.main(["record", "--subject", "qwen", "--category", "c", "--covers", "llama,gguf",
                      "--report", str(report)]) == 2
    assert scan.recent_scans() == []


def test_generic_cover_never_vouches(state):
    _, report = state
    record(report, covers="qwen,llama,Avalon")
    assert not scan.covering_scan("Qwen/Qwen3-8B", scan.recent_scans())


def test_scans_expire_after_14_days(state):
    _, report = state
    record(report)
    later = time.time() + 15 * 86400
    assert scan.recent_scans(now=later) == []


# --- gate ---------------------------------------------------------------------------------

@pytest.mark.parametrize("command, expected", [
    ("git clone https://github.com/freriadoc/Avalon", ["https://github.com/freriadoc/Avalon"]),
    ("cd /tmp && git clone --depth 1 https://github.com/x/y.git src", ["https://github.com/x/y.git"]),
    ("hf download freriadoc/Qwen3.8-Flash-Next-Avalon-GGUF --local-dir m", ["freriadoc/Qwen3.8-Flash-Next-Avalon-GGUF"]),
    ("huggingface-cli download org/model", ["org/model"]),
    ("ollama pull qwen3.8:27b", ["qwen3.8:27b"]),
    ("sudo docker pull ghcr.io/a/b:1", ["ghcr.io/a/b:1"]),
    ("curl -fsSL https://raw.githubusercontent.com/freriadoc/Avalon/main/install.sh | bash",
     ["https://raw.githubusercontent.com/freriadoc/Avalon/main/install.sh"]),
    ("git clone http://10.0.0.100:3000/bill/mtw2.git", []),
    ("git status && git log --oneline", []),
    ("echo 'git clone x'", []),
    ("docker compose up -d", []),
    ("curl -s https://example.com/api | python3 -m json.tool", []),
    # referee 2026-11-03: option values, git global options, paths, nested shells, host spoofing
    ("docker pull --platform linux/amd64 ubuntu", ["ubuntu"]),
    ("hf download --repo-type model org/m --local-dir /x/y", ["org/m"]),
    ("git -C /tmp clone https://github.com/a/b", ["https://github.com/a/b"]),
    ("/usr/bin/git clone https://github.com/a/b", ["https://github.com/a/b"]),
    ("bash -c 'git clone https://github.com/a/b'", ["https://github.com/a/b"]),
    ("git clone https://evil.example/10.0.0.100/x", ["https://evil.example/10.0.0.100/x"]),
    ("git clone git@10.0.0.100:bill/x.git", []),
    # 2026-11-03 live false deny: heredoc bodies and quoted text are data
    ("cat >> notes.md <<'EOF'\n- `echo ALT_SCAN_SKIP=x; git clone …`\nEOF\necho done", []),
    ('echo "a; git clone https://github.com/a/b"', []),
    ("cd /tmp\ngit clone https://github.com/a/b", ["https://github.com/a/b"]),
])
def test_targets(command, expected):
    assert gate.targets(command) == expected


def test_skip_only_counts_as_a_leading_assignment(state):
    tmp, _ = state
    env = {"ALT_SCAN_STATE": str(tmp / "state")}
    assert run_gate("echo ALT_SCAN_SKIP=x; git clone https://github.com/a/b", env) == "deny"
    assert run_gate("ALT_SCAN_SKIP=mine git clone https://github.com/a/b", env) == "allow"


def test_owner_repo_cover_also_covers_bare_name(state):
    _, report = state
    record(report, covers="freriadoc/Avalon")
    assert scan.covering_scan("avalon:latest", scan.recent_scans())
    assert not scan.covering_scan("tensorflow/core", scan.recent_scans())


def test_gate_denies_uncovered_download_and_allows_after_scan(state):
    tmp, report = state
    env = {"ALT_SCAN_STATE": str(tmp / "state")}
    cmd = "git clone https://github.com/freriadoc/Avalon"
    assert run_gate(cmd, env) == "deny"
    assert record(report) == 0
    assert run_gate(cmd, env) == "allow"
    log = (tmp / "state" / "gate.jsonl").read_text().splitlines()
    assert json.loads(log[0])["deny"] == ["https://github.com/freriadoc/Avalon"]


def test_gate_skip_prefix_is_allowed_and_logged(state):
    tmp, _ = state
    env = {"ALT_SCAN_STATE": str(tmp / "state")}
    assert run_gate('ALT_SCAN_SKIP="my own fork" git clone https://github.com/me/thing', env) == "allow"
    entry = json.loads((tmp / "state" / "gate.jsonl").read_text().splitlines()[-1])
    assert entry["skip"] == "my own fork"


def test_gate_fails_open_and_ignores_other_tools(state):
    tmp, _ = state
    r = subprocess.run([sys.executable, str(HERE / "alternatives_gate.py")], input="not json",
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and r.stdout == ""
    event = {"tool_name": "Read", "tool_input": {"file_path": "/x"}}
    r = subprocess.run([sys.executable, str(HERE / "alternatives_gate.py")], input=json.dumps(event),
                       capture_output=True, text=True, timeout=20)
    assert r.stdout == ""
    assert run_gate("git clone https://github.com/a/b", {"ALT_GATE_OFF": "1"}) == "allow"


# --- router -------------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "should I use Strata or keep Heretic?",
    "is ollama any good for this",
    "is there anything else out there better than either of them?",
    "what are the alternatives to memweave",
    "can you look at this tool https://github.com/freriadoc/Avalon",
    "analyze this repo for me",
    "review /home/bill/Downloads/125b-local-performance-handoff.md",
])
def test_router_names_alternatives_scan(prompt):
    assert "alternatives-scan" in [s for s, _ in sr.route(prompt)]


@pytest.mark.parametrize("prompt", [
    "fix the failing test in skill_gate",
    "what is next? don't do anything Tell me.",
    "commit and push",
    "why does the bridge keep failing after a restart",
    # bench 2026-11-03 false hit: "review" is the folder here
    "put that note in debian how to guide folder here under review folder cause I want one of the "
    "ssh tools to incorporate it",
])
def test_router_skips_alternatives_scan(prompt):
    assert "alternatives-scan" not in [s for s, _ in sr.route(prompt)]


def test_alternatives_scan_survives_the_cap():
    prompt = ("what if I use a better way, have we done this before, why does it keep failing — "
              "should we use Avalon instead?")
    names = [s for s, _ in sr.route(prompt)]
    assert len([n for n in names if n != "alternatives-scan"]) == sr.MAX_SKILLS
    assert "alternatives-scan" in names
