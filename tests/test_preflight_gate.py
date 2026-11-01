"""scripts/preflight_gate.py: a trusted repo's declared checks run before matching Bash commands."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import preflight_gate as pg  # noqa: E402


@pytest.fixture(autouse=True)
def _no_log(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "LOG", tmp_path / "nolog" / "hook-blocks.log")


def make_repo(tmp_path, config: str | None) -> Path:
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "sub").mkdir()
    if config is not None:
        (root / ".claude").mkdir()
        (root / ".claude" / "preflight.toml").write_text(config)
    return root


def call(root: Path, command: str, *, cwd=None, tool="Bash", trusted=None, capsys=None):
    data = {"tool_name": tool, "tool_input": {"command": command},
            "cwd": str(cwd or root), "session_id": "t"}
    rc = pg.main(io.StringIO(json.dumps(data)), trusted={root.resolve()} if trusted is None else trusted)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else None)


GATE = """
[[gate]]
id = "quiet-world"
match = '(?:^|[;&|(]\\s*)(?:\\w+=\\S*\\s+)*just\\s+qa(?![\\w-])'
run = "{run}"
why = "no papal elections mid-test"
"""


def test_matching_command_denied_when_check_fails(tmp_path, capsys):
    root = make_repo(tmp_path, GATE.format(run="echo papal_election open; exit 3"))
    rc, out = call(root, "just qa field", capsys=capsys)
    assert rc == 0
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "quiet-world" in hso["permissionDecisionReason"]
    assert "papal_election open" in hso["permissionDecisionReason"]
    assert "no papal elections mid-test" in hso["permissionDecisionReason"]


def test_matching_command_allowed_when_check_passes(tmp_path, capsys):
    root = make_repo(tmp_path, GATE.format(run="exit 0"))
    assert call(root, "PARLEY_NO_X_INPUT=1 just qa field", capsys=capsys) == (0, None)


def test_check_sees_the_command_and_runs_from_repo_root(tmp_path, capsys):
    root = make_repo(tmp_path, GATE.format(
        run='test \\"$PREFLIGHT_COMMAND\\" = \\"cd x; just qa all\\" && test -d .claude'))
    assert call(root, "cd x; just qa all", cwd=root / "sub", capsys=capsys) == (0, None)


def test_non_matching_command_is_not_checked(tmp_path, capsys):
    root = make_repo(tmp_path, GATE.format(run="exit 1"))
    for cmd in ("just test", "just qa-restore", "grep 'just qa' README.md", "echo hi"):
        assert call(root, cmd, capsys=capsys) == (0, None), cmd


def test_cd_into_a_gated_repo_from_elsewhere_still_meets_its_gate(tmp_path, capsys):
    # 11-01: the gate read only the session cwd, so `cd mtw2 && just qa` from Uncle J slipped by
    root = make_repo(tmp_path, GATE.format(run="exit 1"))
    elsewhere = tmp_path / "other"
    (elsewhere / ".git").mkdir(parents=True)
    for cmd in (f"cd {root} && just qa field", f"cd '{root}/sub'; just qa field",
                f"pushd {root} && just qa all"):
        rc, out = call(root, cmd, cwd=elsewhere, capsys=capsys)
        assert out and out["hookSpecificOutput"]["permissionDecision"] == "deny", cmd
    assert call(root, f"cd {root} && just test", cwd=elsewhere, capsys=capsys) == (0, None)


def test_command_dirs_resolves_relative_and_dash_c(tmp_path):
    dirs = pg.command_dirs("git -C ../x status; cd sub && ls", str(tmp_path))
    assert dirs[0] == str(tmp_path)
    assert set(dirs[1:]) == {str(tmp_path / "../x"), str(tmp_path / "sub")}


def test_untrusted_repo_never_runs_its_gate(tmp_path, capsys):
    marker = tmp_path / "ran"
    root = make_repo(tmp_path, GATE.format(run=f"touch {marker}; exit 1"))
    assert call(root, "just qa field", trusted=set(), capsys=capsys) == (0, None)
    assert not marker.exists()


def test_no_config_or_other_tool_is_silent(tmp_path, capsys):
    root = make_repo(tmp_path, None)
    assert call(root, "just qa field", capsys=capsys) == (0, None)
    root2 = make_repo(tmp_path / "b", GATE.format(run="exit 1"))
    assert call(root2, "just qa field", tool="Read", capsys=capsys) == (0, None)


def test_config_above_git_root_is_ignored(tmp_path, capsys):
    outer = tmp_path / "outer"
    (outer / ".claude").mkdir(parents=True)
    (outer / ".claude" / "preflight.toml").write_text(GATE.format(run="exit 1"))
    inner = outer / "inner"
    (inner / ".git").mkdir(parents=True)
    assert pg.find_config(str(inner)) is None


def test_broken_config_denies_every_command(tmp_path, capsys):
    root = make_repo(tmp_path, "[[gate]\nid = ")
    rc, out = call(root, "ls", capsys=capsys)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "preflight.toml" in reason and "Edit tool" in reason


@pytest.mark.parametrize("cfg", [
    '[[gate]]\nid = "x"\nrun = "true"\n',                       # no match
    '[[gate]]\nid = "x"\nmatch = "("\nrun = "true"\n',          # bad regex
    '[[gate]]\nid = "x"\nmatch = "a"\nrun = "true"\ntimeout = -1\n',
    'gate = "nope"\n',
])
def test_invalid_gate_definitions_are_config_errors(tmp_path, cfg):
    root = make_repo(tmp_path, cfg)
    with pytest.raises(ValueError):
        pg.load_gates(root / ".claude" / "preflight.toml")


def test_timeout_is_capped_and_a_slow_check_denies(tmp_path, capsys, monkeypatch):
    root = make_repo(tmp_path, GATE.format(run="sleep 5") + "timeout = 500\n")
    gates = pg.load_gates(root / ".claude" / "preflight.toml")
    assert gates[0]["_timeout"] == pg.MAX_TIMEOUT
    monkeypatch.setattr(pg, "MAX_TIMEOUT", 0.3)
    rc, out = call(root, "just qa field", capsys=capsys)
    assert "did not finish" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_trusted_roots_parses_comments_and_blank_lines(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text(f"# header\n\n{tmp_path}/a  # mine\n{tmp_path}/b\n")
    assert pg.trusted_roots(f) == {(tmp_path / "a").resolve(), (tmp_path / "b").resolve()}
    assert pg.trusted_roots(tmp_path / "missing") == set()


def test_wrapper_fails_open_on_garbage_and_denies_through_symlink(tmp_path):
    sh = REPO / "hooks" / "discipline" / "preflight-gate.sh"
    link = tmp_path / "hooks" / "discipline" / "preflight-gate.sh"
    link.parent.mkdir(parents=True)
    link.symlink_to(sh)
    r = subprocess.run(["bash", str(link)], input="not json", capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
    # mtw2 is trusted in the shipped list; a non-Bash call there is still silent
    data = json.dumps({"tool_name": "Read", "tool_input": {}, "cwd": "/opt/proj/games/mtw2"})
    r = subprocess.run(["bash", str(link)], input=data, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
