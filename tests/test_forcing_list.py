"""scripts/forcing_list.py: every event a project's tests depend on is forced, unforceable with a reason, or parked with an idea."""
import datetime as dt
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "forcing_list.py"
_spec = importlib.util.spec_from_file_location("forcing_list", SCRIPT)
fl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fl)

TODAY = dt.date(2026, 11, 6)


def write(tmp_path, body, name=".claude/events.toml"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    (tmp_path / "bench.py").write_text("def force_marriage():\n    pass\n")
    return p


def problems(tmp_path, body):
    return fl.check(fl.load(write(tmp_path, body)), tmp_path, TODAY)


def test_a_forced_event_with_proof_passes(tmp_path):
    assert problems(tmp_path, """
[events.marriage]
what = "a wife offer"
force = "just qa marriage"
force_proof = ["bench.py::def force_marriage"]
""") == []


def test_a_force_with_no_proof_fails(tmp_path):
    assert "force_proof" in problems(tmp_path, '[events.m]\nwhat = "x"\nforce = "just qa"\n')[0]


def test_a_force_whose_proof_does_not_match_fails(tmp_path):
    p = problems(tmp_path, '[events.m]\nwhat = "x"\nforce = "y"\nforce_proof = ["bench.py::def nothing_like_it"]\n')
    assert "bench.py" in p[0]


def test_a_force_proof_naming_a_missing_file_fails(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nforce = "y"\nforce_proof = ["gone.py::a"]\n')


def test_a_proof_outside_the_repo_does_not_count(tmp_path):
    (tmp_path.parent / "outside.py").write_text("hit\n")
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nforce = "y"\nforce_proof = ["../outside.py::hit"]\n')


def test_a_bad_proof_regex_is_a_problem_not_a_crash(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nforce = "y"\nforce_proof = ["bench.py::("]\n')


def test_a_malformed_proof_entry_is_a_problem(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nforce = "y"\nforce_proof = ["no separator"]\n')


def test_a_reason_it_cannot_be_forced_passes(tmp_path):
    assert problems(tmp_path, '[events.draw]\nwhat = "a future draw"\ncannot_force = "forcing it ruins the test"\n') == []


def test_an_empty_reason_does_not_count(tmp_path):
    assert problems(tmp_path, '[events.draw]\nwhat = "x"\ncannot_force = "  "\n')


def test_a_parked_row_with_an_idea_and_a_future_date_passes(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nidea = "edit the save"\nparked_until = 2026-12-01\n') == []


def test_the_date_can_be_a_string(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nidea = "edit the save"\nparked_until = "2026-12-01"\n') == []


def test_a_parked_row_past_its_date_fails(tmp_path):
    assert "2026-11-01" in problems(tmp_path, '[events.m]\nwhat = "x"\nidea = "y"\nparked_until = 2026-11-01\n')[0]


def test_parking_without_an_idea_fails(tmp_path):
    # The idea is the point: "how would I force this?" has to get an answer.
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nparked_until = 2026-12-01\n')


def test_an_idea_with_no_date_fails(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nidea = "y"\n')


def test_a_bad_date_is_a_problem_not_a_crash(tmp_path):
    assert problems(tmp_path, '[events.m]\nwhat = "x"\nidea = "y"\nparked_until = "soon"\n')


def test_an_untriaged_row_fails_and_names_itself(tmp_path):
    p = problems(tmp_path, '[events.papal_missions]\nwhat = "papal requests"\n')
    assert "papal_missions" in p[0] and "cannot_force" in p[0]


def test_saying_both_forced_and_unforceable_fails(tmp_path):
    assert problems(tmp_path, """
[events.m]
what = "x"
force = "y"
force_proof = ["bench.py::def force_marriage"]
cannot_force = "z"
""")


def test_a_row_needs_what_it_is(tmp_path):
    assert problems(tmp_path, '[events.m]\ncannot_force = "z"\n')


def test_other_fields_in_a_shared_file_are_left_alone(tmp_path):
    # mtw2's games/interrupts.toml uses `proof` and `held_by` for holding events off.
    assert problems(tmp_path, """
[events.pope]
what = "the Pope dies"
held_by = "M.qa.quiet"
proof = ["gone.py::not this list's business"]
cannot_force = "z"
""") == []


def run(tmp_path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp_path, capture_output=True, text=True)


def test_cli_passes_on_a_clean_list(tmp_path):
    write(tmp_path, '[events.m]\nwhat = "x"\ncannot_force = "z"\n')
    assert run(tmp_path).returncode == 0


def test_cli_fails_with_the_fix_in_its_output(tmp_path):
    write(tmp_path, '[events.m]\nwhat = "x"\n')
    r = run(tmp_path)
    assert r.returncode == 1 and "events.m" in r.stdout and "force" in r.stdout


def test_cli_fails_when_a_gate_points_at_a_missing_list(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 1 and "events.toml" in r.stdout


def test_cli_fails_on_broken_toml(tmp_path):
    write(tmp_path, "[events.m\n")
    r = run(tmp_path)
    assert r.returncode == 1 and "Traceback" not in r.stderr


def test_cli_reads_another_file(tmp_path):
    write(tmp_path, '[events.m]\nwhat = "x"\ncannot_force = "z"\n', name="games/interrupts.toml")
    assert run(tmp_path, "--file", "games/interrupts.toml").returncode == 0


def test_list_shows_every_state_and_never_fails_on_open_rows(tmp_path):
    write(tmp_path, """
[events.a]
what = "forced one"
force = "just x"
force_proof = ["bench.py::def force_marriage"]
[events.b]
what = "unforceable"
cannot_force = "z"
[events.c]
what = "parked"
idea = "edit the save"
parked_until = 2099-01-01
[events.d]
what = "open one"
""")
    r = run(tmp_path, "--list")
    assert r.returncode == 0
    for word in ("forced", "cannot force", "parked", "OPEN"):
        assert word in r.stdout
