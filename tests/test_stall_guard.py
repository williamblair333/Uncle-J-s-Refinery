"""hooks/discipline/stall_guard.py: waits that can hang without telling anyone."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks" / "discipline"
sys.path.insert(0, str(HOOKS))
import stall_guard as sg  # noqa: E402

# mtw2's tc queue on 11-21, as it ran (hung 12:19-15:28)
MTW2_HUNG = ("ssh tc 'until grep -q \"click coverage:\" /tmp/a.out; do sleep 20; done; "
             "while pgrep -f \"[p]ython3 scripts/click_coverage.py\" >/dev/null; do sleep 5; done; "
             "cd /x; python3 scripts/click_coverage.py'")
# write-well's 11-21 wait: every waiting shell matched every other's grep
WW_PSGREP = ("while ps aux | grep -q 'comfy_job.py'; do sleep 30; done; "
             "timeout 900 python3 scripts/comfy_job.py image 'x'")


def rules(cmd, bg=False):
    return {sg._rule(p) for p in sg.problems(cmd, bg)}


def test_the_mtw2_hung_queue_is_refused_for_both_reasons():
    assert {"self-match", "no-clock"} <= rules(MTW2_HUNG, bg=True)


def test_self_match_is_refused_in_the_foreground_too():
    assert "self-match" in rules(MTW2_HUNG)


def test_write_wells_ps_grep_wait_is_a_self_match():
    assert "self-match" in rules(WW_PSGREP, bg=True)


def test_ps_grep_v_grep_is_not_a_self_match():
    assert "self-match" not in rules("while ps aux | grep -v grep | grep -q x; do sleep 5; done")


def test_pkill_that_would_kill_its_own_shell():
    # from the 30-day replay: "[w]atch" matches "just watch" in the same command
    assert "self-match" in rules("pkill -f '[w]atch'; sleep 1; just watch scratch")


def test_a_pgrep_that_only_lists_is_not_refused():
    # replay false hits: the output is read, a self-line is noise, not a hang
    assert "self-match" not in rules("pgrep -af 'crash' | grep -v pgrep | head; tail logs/crash-watch.log")


def test_a_loop_that_skips_its_own_shell_is_not_refused():
    cmd = ('for p in $(pgrep -f "dingwatch.sh"); do [ "$p" != "$$" ] && kill $p; done; '
           "pgrep -af dingwatch.sh")
    assert "self-match" not in rules(cmd)


def test_pkill_x_f_matches_whole_lines_only():
    assert "self-match" not in rules('pkill -x -f "bash /tmp/chain.sh"; echo bash /tmp/chain.sh')


def test_a_pkill_that_kills_the_shell_running_it():
    assert "self-match" in rules('pkill -f "pytest -q"; sleep 1; timeout 100 uv run pytest -q')


def test_a_pgrep_used_as_a_test_is_refused():
    assert "self-match" in rules("pgrep -f crash_watch >/dev/null || bash crash_watch.sh")


def test_a_pgrep_pattern_found_nowhere_else_passes():
    assert rules("pgrep -f '[j]ust qa' | head") == set()


def test_pgrep_by_exact_name_is_not_checked():
    assert rules("pgrep -x python3; echo python3") == set()


def test_prose_naming_pgrep_is_not_a_pgrep():
    assert rules('git commit -m "its pgrep -f matched its own bash -c line"') == set()


def test_a_foreground_loop_has_the_tool_timeout_as_its_clock():
    assert "no-clock" not in rules("until [ -f done ]; do sleep 5; done")


def test_a_background_loop_with_date_of_any_format_has_a_clock():
    # the replay's false hit: `date +%H%M` is a clock too
    assert "no-clock" not in rules('until [ "$(date +%H%M)" -ge 1014 ]; do sleep 20; done', bg=True)


def test_a_background_wait_with_seconds_passes():
    cmd = ("while :; do grep -q DONE f && break; (( SECONDS > 600 )) && { echo STALLED; break; }; "
           "sleep 30; done")
    assert "no-clock" not in rules(cmd, bg=True)


def test_background_pipe_hides_the_exit_code():
    # write-well 11-21: `just fixes ... | tail` hid a RAM-floor stop
    assert "hidden-exit" in rules("timeout 3600 just fixes jobs.tsv | tail -20", bg=True)


def test_pipefail_or_a_quoted_pipe_is_fine():
    assert "hidden-exit" not in rules("set -o pipefail; timeout 60 make | tail", bg=True)
    assert "hidden-exit" not in rules('timeout 60 echo "a | b"', bg=True)
    assert "hidden-exit" not in rules("timeout 60 a || b", bg=True)


def test_background_without_timeout_and_the_opt_out():
    assert "no-deadline" in rules("just qa navy", bg=True)
    assert "no-deadline" not in rules("timeout 1800 just qa navy", bg=True)
    assert "no-deadline" not in rules("npm run dev  # no-deadline: dev server", bg=True)
    assert "no-deadline" not in rules("just qa navy")  # foreground: the tool's timeout


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "STATE", tmp_path)
    return tmp_path


def payload(cmd, bg=False, session="s1"):
    return {"tool_name": "Bash", "session_id": session,
            "tool_input": {"command": cmd, "run_in_background": bg}}


def test_advice_refuses_once_per_session_then_lets_it_run(state):
    first = sg.decide(payload("just qa navy", bg=True))
    assert len(first) == 1 and first[0].startswith("no-deadline")
    assert sg.decide(payload("just qa navy", bg=True)) == []
    assert sg.decide(payload("just qa other", bg=True)) == []
    assert sg.decide(payload("just qa navy", bg=True, session="s2"))  # a new session hears it


def test_hard_rules_refuse_every_time(state):
    for _ in range(3):
        assert any(p.startswith("self-match") for p in sg.decide(payload(MTW2_HUNG)))


def test_advice_is_not_repeated_forever_when_state_is_unwritable(state, monkeypatch):
    monkeypatch.setattr(sg, "_mark", lambda *a: False)
    assert sg.decide(payload("just qa navy", bg=True)) == []


def test_other_tools_pass(state):
    assert sg.decide({"tool_name": "Read", "tool_input": {"command": MTW2_HUNG}}) == []


def run_hook(stdin: str, tmp_path):
    env = {**os.environ, "STALL_GUARD_STATE": str(tmp_path), "STALL_GUARD_LOG": str(tmp_path / "log")}
    return subprocess.run(["bash", str(HOOKS / "stall-guard.sh")], input=stdin, text=True,
                          capture_output=True, env=env, timeout=30)


def test_wrapper_blocks_with_exit_2_and_logs(tmp_path):
    r = run_hook(json.dumps(payload(MTW2_HUNG)), tmp_path)
    assert r.returncode == 2 and "self-match" in r.stderr
    assert "BLOCKED stall-guard" in (tmp_path / "log").read_text()


def test_wrapper_fails_open_on_garbage_and_on_a_clean_command(tmp_path):
    assert run_hook("not json", tmp_path).returncode == 0
    assert run_hook(json.dumps(payload("git status")), tmp_path).returncode == 0


# ---- agy review 2026-11-22: each case below was a wrong answer in the first version ----

@pytest.mark.parametrize("cmd", [
    "python3 server.py & sleep 1; pgrep -af server.py",            # listing, not a test
    'git commit -m "pkill -f worker killed worker"',                 # prose in a quoted arg
    'git commit -m "fail if pgrep -f worker matches worker"',
    "rg 'pgrep -f stall' tests/test_stall_guard.py",
    "pgrep -f -P 1 '[w]orker' >/dev/null || sleep 1",                # -P takes a value
    "pkill -f -- '[w]orker'; python3 --version",
    "cat <<'EOF' > s.sh\nwhile pgrep -f x; do sleep 1; done; x\nEOF\n",  # heredoc is data
    "cd /x && cat > restore.sh <<'EOF'\nwhile pgrep -f x; do sleep 1; done; x\nEOF\n",
    "python3 - <<'EOF'\ns = 'while pgrep -f x; do sleep 1; done; x'\nEOF\n",  # python, not shell
])
def test_review_false_blocks_pass(cmd):
    assert "self-match" not in rules(cmd)


@pytest.mark.parametrize("cmd", [
    "while pgrep -f worker.py | grep -q .; do sleep 5; done; python3 worker.py",
    "pkill -u root -f worker; python3 worker",                       # -u value before -f
    "ssh tc 'pkill -f \"[j]ust watch\"; just watch scratch'",
    "bash -c 'while pgrep -f job.sh >/dev/null; do sleep 5; done; bash job.sh'",
    "ssh tc bash <<'EOF'\nwhile pgrep -f job.sh >/dev/null; do sleep 5; done; bash job.sh\nEOF\n",
])
def test_review_false_passes_are_caught(cmd):
    assert "self-match" in rules(cmd)


def test_ps_grep_then_grep_v_grep_is_fine_but_a_later_positive_grep_is_not():
    ok = ("while ps aux | grep 'comfy_job.py' | grep -v grep >/dev/null; do sleep 30; done; "
          "timeout 9 python3 comfy_job.py")
    bad = ("while ps aux | grep -v root | grep -q 'comfy_job.py'; do sleep 30; done; "
           "timeout 9 python3 comfy_job.py")
    assert "self-match" not in rules(ok, bg=True)
    assert "self-match" in rules(bad, bg=True)


@pytest.mark.parametrize("cmd", [
    'while read -r f; do pytest "$f"; done < files.txt; sleep 1',      # loop and sleep apart
    'echo "wait until ready"; for i in {1..30}; do curl -sf x && break; sleep 1; done',
    'until [ "$(date -u +%s)" -ge 1800000000 ]; do sleep 5; done',
    "i=0; while [ $i -lt 30 ]; do [ -f r ] && break; i=$((i+1)); sleep 2; done",
    "timeout -s TERM 60 bash -c 'until [ -f /tmp/ready ]; do sleep 2; done'",
])
def test_review_loops_with_a_bound_pass(cmd):
    assert "no-clock" not in rules(cmd, bg=True)


def test_a_newline_separated_loop_is_still_seen():
    assert "no-clock" in rules("until [ -f /tmp/ready ]\ndo\n  sleep 5\ndone", bg=True)


def test_timeout_with_options_or_a_variable_is_a_deadline():
    for cmd in ("timeout -s TERM 60 make", 'timeout "$T" make', "timeout --kill-after=5 60 make",
                "timeout -k 5 60 make"):
        assert "no-deadline" not in rules(cmd, bg=True), cmd


def test_an_apostrophe_in_a_comment_does_not_eat_the_command():
    assert rules("# don't hang\ntimeout 60 pytest -k 'test_api'", bg=True) == set()
    assert "hidden-exit" in rules("# don't fail\ntimeout 60 make | grep 'error'", bg=True)


def test_a_hard_block_does_not_spend_the_advice(state):
    hard = sg.decide(payload("while pgrep -f app; do sleep 5; done; python3 app", bg=True))
    assert hard and all(not p.startswith("no-deadline") for p in hard)
    assert any(p.startswith("no-deadline") for p in sg.decide(payload("just qa navy", bg=True)))


def test_no_session_id_still_gets_advice_once(state):
    p = {"tool_name": "Bash", "tool_input": {"command": "just qa navy", "run_in_background": True}}
    assert sg.decide(p) and sg.decide(p) == []


def test_run_in_background_must_be_true_not_truthy():
    assert sg.decide({"tool_name": "Bash", "session_id": "x",
                      "tool_input": {"command": "until [ -f d ]; do sleep 5; done",
                                     "run_in_background": "false"}}) == []


def test_a_20kb_heredoc_is_judged_fast():
    import time
    body = "while x; do y; done\n" * 1000 + "until z; do w\n" * 200
    t = time.monotonic()
    sg.problems("cat <<'EOF' > s.sh\n" + body + "EOF\n" + body, background=True)
    assert time.monotonic() - t < 1.0


def test_wrapper_fails_open_when_python_cannot_open_the_script(tmp_path):
    import shutil
    d = tmp_path / "h"
    d.mkdir()
    shutil.copy(HOOKS / "stall-guard.sh", d / "stall-guard.sh")  # no stall_guard.py beside it
    r = subprocess.run(["bash", str(d / "stall-guard.sh")], input=json.dumps(payload(MTW2_HUNG)),
                       text=True, capture_output=True, timeout=30)
    assert r.returncode == 0
