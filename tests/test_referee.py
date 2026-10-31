"""Tests for scripts/referee.py: the cross-provider referee on top of ask_agy.

A fake `agy` replays a stream-json transcript, as in test_ask_agy.py, so no network or
quota is used. The point under test is that the referee never reports a pass it did not
get: an agy failure, an unparseable reply, or a malformed verdict all exit non-zero. And
because the work goes to Google, credential-like inputs are refused before agy runs."""
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ref = load("referee", "scripts/referee.py")


def result(response, status="SUCCESS"):
    return {"event": "result", "result": {"status": status, "response": response, "num_turns": 1}}


def fake_agy(tmp_path, events):
    data = tmp_path / "events.jsonl"
    data.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    argv_log = tmp_path / "argv.json"
    script = tmp_path / "agy"
    script.write_text(
        f"#!{sys.executable}\n"  # not `env python3`: agy's shims are first on PATH
        "import json, sys\n"
        f"json.dump(sys.argv[1:], open({str(argv_log)!r}, 'w'))\n"
        f"sys.stdout.write(open({str(data)!r}).read())\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, argv_log


def verdict(v="pass", findings=None, summary="looks right"):
    return json.dumps({"verdict": v, "findings": findings or [], "summary": summary})


def judge(tmp_path, reply, **kw):
    script, argv_log = fake_agy(tmp_path, [result(reply)])
    kw.setdefault("task", "add a --dry-run flag")
    kw.setdefault("work", "diff --git a/x b/x\n+dry_run = True\n")
    out = ref.referee(agy_bin=str(script), cwd=str(tmp_path), log_path=None, **kw)
    return out, json.loads(argv_log.read_text())


def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)


# ── verdict parsing ─────────────────────────────────────────────────────────────

def test_pass_verdict(tmp_path):
    out, argv = judge(tmp_path, verdict("pass"))
    assert out["verdict"] == "pass" and ref.exit_code(out) == 0
    prompt = argv[argv.index("-p") + 1]
    assert "add a --dry-run flag" in prompt and "+dry_run = True" in prompt
    assert "--mode" not in argv            # the referee never gets write access
    # agy ends a print-mode turn with no answer when it soft-denies a command, so the
    # prompt has to name exactly what is allowed, taken from the shipped allow list.
    assert "git diff" in prompt and "grep" in prompt and "ends your turn" in prompt


def test_fail_verdict_keeps_findings(tmp_path):
    f = [{"severity": "high", "where": "x:1", "problem": "flag never read", "evidence": "grep"}]
    out, _ = judge(tmp_path, verdict("fail", f))
    assert out["verdict"] == "fail" and ref.exit_code(out) == 2
    assert out["findings"][0]["problem"] == "flag never read"


def test_fenced_json_is_accepted(tmp_path):
    out, _ = judge(tmp_path, "Here you go:\n```json\n" + verdict("unsure") + "\n```\n")
    assert out["verdict"] == "unsure" and ref.exit_code(out) == 3


def test_pass_with_high_finding_is_downgraded(tmp_path):
    f = [{"severity": "high", "where": "", "problem": "breaks on empty input"}]
    out, _ = judge(tmp_path, verdict("pass", f))
    assert out["verdict"] == "unsure" and "downgraded" in out["note"]


def test_prose_reply_is_an_error_not_a_pass(tmp_path):
    out, _ = judge(tmp_path, "Looks good to me, ship it!")
    assert out["verdict"] == "error" and ref.exit_code(out) == 1


def test_unknown_verdict_value_is_an_error(tmp_path):
    out, _ = judge(tmp_path, verdict("approved"))
    assert out["verdict"] == "error"


def test_finding_without_problem_is_an_error(tmp_path):
    out, _ = judge(tmp_path, verdict("fail", [{"severity": "high"}]))
    assert out["verdict"] == "error"


def test_agy_failure_is_an_error(tmp_path):
    script, _ = fake_agy(tmp_path, [result("", status="ERROR")])
    out = ref.referee(task="t", work="w", agy_bin=str(script), cwd=str(tmp_path), log_path=None)
    assert out["verdict"] == "error" and ref.exit_code(out) == 1


# ── inputs ──────────────────────────────────────────────────────────────────────

def test_oversized_work_is_refused_not_truncated(tmp_path):
    out = ref.referee(task="t", work="x" * (ref.MAX_WORK_CHARS + 1), agy_bin="/nonexistent",
                      cwd=str(tmp_path), log_path=None)
    assert out["verdict"] == "error" and "narrow" in out["error"]


def test_collect_work_from_git_diff(tmp_path):
    git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("two\n")
    work = ref.collect_work(cwd=str(tmp_path), diff="HEAD")
    assert "-one" in work and "+two" in work


def test_collect_work_from_files(tmp_path):
    (tmp_path / "f.py").write_text("print(1)\n")
    work = ref.collect_work(cwd=str(tmp_path), files=["f.py"])
    assert "f.py" in work and "print(1)" in work


def test_empty_diff_is_an_error(tmp_path):
    git_repo(tmp_path)
    assert ref.main(["--task", "t", "--diff", "--cwd", str(tmp_path), "--agy-bin", "/nonexistent",
                     "--no-log"]) == 1


# ── secrets never leave the machine ─────────────────────────────────────────────

def test_credential_path_is_refused(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    try:
        ref.collect_work(cwd=str(tmp_path), files=[".env"])
    except ref.RefereeInputError as e:
        assert ".env" in str(e)
    else:
        raise AssertionError("credential-like path was accepted")


def test_secret_in_work_is_refused_before_agy_runs(tmp_path):
    script, argv_log = fake_agy(tmp_path, [result(verdict())])
    # Built by concatenation so the repo never holds a literal the healthcheck's
    # tracked-secret scan (sk-lf-*) would flag.
    for secret in ("sk-" + "lf-" + "0123456789abcdef", "-----BEGIN OPENSSH PRIVATE " + "KEY-----",
                   "ghp_" + "a" * 36, "AKIA" + "A" * 16):
        out = ref.referee(task="t", work=f"+key = '{secret}'\n", agy_bin=str(script),
                          cwd=str(tmp_path), log_path=None)
        assert out["verdict"] == "error" and "secret" in out["error"]
    assert not argv_log.exists()           # agy was never called


def test_credential_directories_are_refused(tmp_path):
    for name in ("secrets/token.json", "config/credentials/db.yaml"):
        try:
            ref.collect_work(cwd=str(tmp_path), files=[name])
        except ref.RefereeInputError:
            continue
        raise AssertionError(f"{name} was accepted")


def test_oversized_task_counts_toward_the_cap(tmp_path):
    out = ref.referee(task="t" * ref.MAX_WORK_CHARS, work="w", agy_bin="/nonexistent",
                      cwd=str(tmp_path), log_path=None)
    assert out["verdict"] == "error" and "narrow" in out["error"]


def test_cli_errors_are_json_on_stdout(tmp_path, capsys):
    assert ref.main(["--task-file", str(tmp_path / "missing.md"), "--file", "x",
                     "--cwd", str(tmp_path), "--no-log"]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "error"


# ── model: the point is a different provider ───────────────────────────────────

def test_gemini_is_pinned_by_default(tmp_path):
    _, argv = judge(tmp_path, verdict())
    assert argv[argv.index("--model") + 1].startswith("gemini")


def test_claude_model_is_refused(tmp_path):
    out = ref.referee(task="t", work="w", model="claude-opus-5-5-high", agy_bin="/nonexistent",
                      cwd=str(tmp_path), log_path=None)
    assert out["verdict"] == "error" and "provider" in out["error"]


# ── measurement log ─────────────────────────────────────────────────────────────

def test_log_records_verdict_not_content(tmp_path):
    script, _ = fake_agy(tmp_path, [result(verdict("fail", [{"severity": "low", "problem": "p"}]))])
    log = tmp_path / "referee.jsonl"
    ref.referee(task="hidden task", work="hidden work", agy_bin=str(script), cwd=str(tmp_path),
                log_path=log)
    line = json.loads(log.read_text().splitlines()[0])
    assert line["verdict"] == "fail" and line["findings"] == 1
    assert "hidden" not in log.read_text()


# ── retry once on a soft deny ───────────────────────────────────────────────────
#    agy sometimes runs a command outside the allow list despite the prompt, then ends
#    the turn with no answer. The same review passed on a re-run, so retry exactly once,
#    naming what was blocked. Other failures (timeouts, bad JSON) are not retried.

def blocked_step(cmd="python3 -c 'print(1)'"):
    return {"step_update": {"step_type": "tool", "state": "ERROR", "tool_name": "run_command",
                            "tool_info": {"parameters": {"CommandLine": cmd},
                                          "error": {"message": "denied by policy"}}}}


def sequenced_agy(tmp_path, runs):
    """A fake agy that replays runs[0] on the first call, runs[1] on the second, ..."""
    for i, events in enumerate(runs):
        (tmp_path / f"run{i}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    calls = tmp_path / "calls.jsonl"
    script = tmp_path / "agy"
    script.write_text(
        f"#!{sys.executable}\n"  # not `env python3`: agy's shims are first on PATH
        "import json, sys, os\n"
        f"calls = {str(calls)!r}\n"
        "n = sum(1 for _ in open(calls)) if os.path.exists(calls) else 0\n"
        "open(calls, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"sys.stdout.write(open(os.path.join({str(tmp_path)!r}, f'run{{n}}.jsonl')).read())\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, calls


def run_ref(tmp_path, runs, log_path=None):
    script, calls = sequenced_agy(tmp_path, runs)
    out = ref.referee(task="add a --dry-run flag", work="+dry_run = True\n", agy_bin=str(script),
                      cwd=str(tmp_path), log_path=log_path)
    return out, [json.loads(l) for l in calls.read_text().splitlines()]


def test_soft_deny_is_retried_once_and_can_pass(tmp_path):
    out, calls = run_ref(tmp_path, [[blocked_step(), result("")], [result(verdict("pass"))]])
    assert len(calls) == 2
    assert out["verdict"] == "pass" and out.get("retried") is True
    retry_prompt = calls[1][calls[1].index("-p") + 1]
    assert "python3 -c 'print(1)'" in retry_prompt          # names what was blocked
    assert "git diff" in retry_prompt                       # restates what is allowed


def test_auto_denied_action_is_retried(tmp_path):
    denied = {"event": "result", "result": {"status": "SUCCESS", "response": "",
                                            "denied_actions": [{"display_name": "rm -rf x"}]}}
    out, calls = run_ref(tmp_path, [[denied], [result(verdict("fail", [
        {"severity": "low", "where": "", "problem": "p"}]))]])
    assert len(calls) == 2 and out["verdict"] == "fail" and out["retried"] is True


def test_second_soft_deny_is_an_error_not_a_third_call(tmp_path):
    out, calls = run_ref(tmp_path, [[blocked_step(), result("")], [blocked_step("sed -n 1p x"), result("")]])
    assert len(calls) == 2
    assert out["verdict"] == "error" and ref.exit_code(out) != 0
    assert "retry" in out["error"]


def test_non_deny_failure_is_not_retried(tmp_path):
    out, calls = run_ref(tmp_path, [[result("not json at all")], [result(verdict("pass"))]])
    assert len(calls) == 1 and out["verdict"] == "error"
    sub = tmp_path / "status-error"
    sub.mkdir()
    out, calls = run_ref(sub, [[result("", status="ERROR")], [result(verdict("pass"))]])
    assert len(calls) == 1 and out["verdict"] == "error"


def test_retry_with_unparseable_reply_still_marks_retried(tmp_path):
    # found by the referee itself when it reviewed this change
    log = tmp_path / "referee.jsonl"
    out, calls = run_ref(tmp_path, [[blocked_step(), result("")], [result("no json here")]],
                         log_path=log)
    assert len(calls) == 2 and out["verdict"] == "error" and out["retried"] is True
    assert json.loads(log.read_text().splitlines()[0])["retried"] is True


def test_log_marks_retried(tmp_path):
    log = tmp_path / "referee.jsonl"
    run_ref(tmp_path, [[blocked_step(), result("")], [result(verdict("pass"))]], log_path=log)
    assert json.loads(log.read_text().splitlines()[0])["retried"] is True
