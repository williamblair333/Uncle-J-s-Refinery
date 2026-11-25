"""Tests for scripts/ci_red_alert.py."""

import importlib.util
import json
import subprocess
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ci_red_alert", REPO / "scripts" / "ci_red_alert.py")
ci_alert = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_alert)


def test_red_alerts_once_and_not_twice_for_same_id():
    run = {
        "databaseId": 1001,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "ci: broken test",
        "url": "https://github.com/org/repo/actions/runs/1001",
    }
    msg1, state1 = ci_alert.decide(run, {}, now=1000)
    assert msg1 == "failure: ci: broken test\nhttps://github.com/org/repo/actions/runs/1001"
    assert state1.get("last_red_id") == 1001

    # Second check for same id sends nothing
    msg2, state2 = ci_alert.decide(run, state1, now=1060)
    assert msg2 is None
    assert state2.get("last_red_id") == 1001


def test_new_red_id_alerts_again():
    run1 = {
        "databaseId": 1001,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "ci: first failure",
        "url": "https://github.com/org/repo/actions/runs/1001",
    }
    _, state1 = ci_alert.decide(run1, {}, now=1000)

    run2 = {
        "databaseId": 1002,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "ci: second failure",
        "url": "https://github.com/org/repo/actions/runs/1002",
    }
    msg2, state2 = ci_alert.decide(run2, state1, now=1100)
    assert msg2 == "failure: ci: second failure\nhttps://github.com/org/repo/actions/runs/1002"
    assert state2.get("last_red_id") == 1002


def test_success_after_red_sends_one_recovery():
    run_red = {
        "databaseId": 1001,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "ci: fail",
        "url": "https://github.com/org/repo/actions/runs/1001",
    }
    _, state_red = ci_alert.decide(run_red, {}, now=1000)

    run_success = {
        "databaseId": 1002,
        "conclusion": "success",
        "status": "completed",
        "displayTitle": "ci: fixed",
        "url": "https://github.com/org/repo/actions/runs/1002",
    }
    msg_rec, state_rec = ci_alert.decide(run_success, state_red, now=1100)
    assert msg_rec == "success: ci: fixed\nhttps://github.com/org/repo/actions/runs/1002"
    assert state_rec.get("last_red_id") is None

    # Subsequent success checks send nothing
    msg_none, state_none = ci_alert.decide(run_success, state_rec, now=1200)
    assert msg_none is None
    assert state_none.get("last_red_id") is None


def test_success_with_no_prior_red_sends_nothing():
    run_success = {
        "databaseId": 1000,
        "conclusion": "success",
        "status": "completed",
        "displayTitle": "ci: green build",
        "url": "https://github.com/org/repo/actions/runs/1000",
    }
    msg, state = ci_alert.decide(run_success, {}, now=1000)
    assert msg is None
    assert state.get("last_red_id") is None


def test_in_progress_sends_nothing():
    run_ip = {
        "databaseId": 1005,
        "conclusion": None,
        "status": "in_progress",
        "displayTitle": "ci: working",
        "url": "https://github.com/org/repo/actions/runs/1005",
    }
    # Empty state
    msg, state = ci_alert.decide(run_ip, {}, now=1000)
    assert msg is None

    # Prior red state preserved
    prior_state = {"last_red_id": 999}
    msg2, state2 = ci_alert.decide(run_ip, prior_state, now=1000)
    assert msg2 is None
    assert state2.get("last_red_id") == 999


def test_unreadable_under_24h_sends_nothing():
    msg1, state1 = ci_alert.decide(None, {}, now=1000)
    assert msg1 is None
    assert state1.get("first_unreadable_at") == 1000
    assert not state1.get("unreadable_alert_sent")

    # 23 hours later: still within 24h, send nothing
    now_23h = 1000 + (23 * 3600)
    msg2, state2 = ci_alert.decide(None, state1, now=now_23h)
    assert msg2 is None
    assert state2.get("first_unreadable_at") == 1000
    assert not state2.get("unreadable_alert_sent")


def test_unreadable_past_24h_sends_once_only():
    msg1, state1 = ci_alert.decide(None, {}, now=1000)
    assert msg1 is None

    # Exactly 24 hours later
    now_24h = 1000 + (24 * 3600)
    msg2, state2 = ci_alert.decide(None, state1, now=now_24h)
    assert msg2 == "can't read CI"
    assert state2.get("unreadable_alert_sent") is True

    # 25 hours later: still failing, but alerted already once
    now_25h = 1000 + (25 * 3600)
    msg3, state3 = ci_alert.decide(None, state2, now=now_25h)
    assert msg3 is None
    assert state3.get("unreadable_alert_sent") is True


def test_reading_successfully_clears_unreadable_timer():
    state_unreadable = {
        "first_unreadable_at": 1000,
        "unreadable_alert_sent": True,
        "last_red_id": 500,
    }
    run = {
        "databaseId": 501,
        "conclusion": "success",
        "status": "completed",
        "displayTitle": "ci: recovery after downtime",
        "url": "https://github.com/org/repo/actions/runs/501",
    }
    msg, state = ci_alert.decide(run, state_unreadable, now=1000 + 30 * 3600)
    assert msg == "success: ci: recovery after downtime\nhttps://github.com/org/repo/actions/runs/501"
    assert state.get("first_unreadable_at") is None
    assert state.get("unreadable_alert_sent") is None

    # Next failure starts a fresh timer
    msg_fail, state_fail = ci_alert.decide(None, state, now=500000)
    assert msg_fail is None
    assert state_fail.get("first_unreadable_at") == 500000


def test_unreadable_does_not_clear_red_state():
    state_red = {"last_red_id": 888}
    _, state_after = ci_alert.decide(None, state_red, now=1000)
    assert state_after.get("last_red_id") == 888


def test_corrupt_or_missing_state_file_is_treated_as_empty(tmp_path):
    missing_path = tmp_path / "nonexistent.json"
    assert ci_alert.load_state(missing_path) == {}

    corrupt_json = tmp_path / "bad.json"
    corrupt_json.write_text("{this is not json")
    assert ci_alert.load_state(corrupt_json) == {}

    non_dict_json = tmp_path / "array.json"
    non_dict_json.write_text("[1, 2, 3]")
    assert ci_alert.load_state(non_dict_json) == {}


def test_save_state_atomicity(tmp_path):
    state_path = tmp_path / "nested" / "ci-red-alert.json"
    data = {"last_red_id": 42, "first_unreadable_at": 12345.0}
    ci_alert.save_state(state_path, data)
    assert ci_alert.load_state(state_path) == data


class _Body:
    def __init__(self, payload):
        self._raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(payload):
    return lambda url, timeout: _Body(payload)


def _raise(err):
    def opener(url, timeout):
        raise err
    return opener


SHA = "c1e7576d6f1541c4b34098341c8811cd425fb922"


def test_fetch_reads_mains_combined_status_on_gitea():
    seen = {}

    def opener(url, timeout):
        seen["url"] = url
        return _Body({"state": "success", "sha": SHA, "statuses": [
            {"status": "success", "context": "CI / lint", "target_url": "/bill/x/actions/runs/1/jobs/1"}]})

    run = ci_alert.fetch_latest_run(urlopen=opener)
    assert seen["url"].endswith("/repos/bill/Uncle-J-s-Refinery/commits/main/status")
    assert run["status"] == "completed" and run["conclusion"] == "success"
    assert run["databaseId"] == SHA


def test_fetch_red_points_at_the_failing_job():
    run = ci_alert.fetch_latest_run(urlopen=_serve({"state": "failure", "sha": SHA, "statuses": [
        {"status": "success", "context": "CI / lint", "target_url": "/bill/x/actions/runs/9/jobs/1"},
        {"status": "failure", "context": "CI / pytest", "description": "Failing after 2m",
         "target_url": "/bill/x/actions/runs/9/jobs/2"}]}))
    assert run["conclusion"] == "failure"
    assert run["url"] == ci_alert.GITEA_WEB + "/bill/x/actions/runs/9/jobs/2"
    assert "CI / pytest" in run["displayTitle"] and SHA[:7] in run["displayTitle"]


def test_fetch_pending_is_in_progress():
    assert ci_alert.fetch_latest_run(urlopen=_serve(
        {"state": "pending", "sha": SHA, "statuses": [{"status": "pending"}]}))["status"] == "in_progress"


def test_fetch_no_statuses_counts_as_unreadable():
    # No CI ran for main's head: must start the 24 h "can't read CI" timer, not stay quiet.
    assert ci_alert.fetch_latest_run(urlopen=_serve({"state": "", "sha": SHA, "statuses": []})) is None


def test_fetch_stack_down_is_offline_not_unreadable():
    import urllib.error
    run = ci_alert.fetch_latest_run(urlopen=_raise(urllib.error.URLError(ConnectionRefusedError(111, "refused"))))
    assert run == ci_alert.OFFLINE
    # offline never starts the 24 h "can't read CI" timer, and keeps red state
    msg, state = ci_alert.decide(run, {"last_red_id": SHA}, now=1000.0)
    assert msg is None and "first_unreadable_at" not in state and state["last_red_id"] == SHA


def test_fetch_other_failures_are_unreadable():
    import urllib.error
    assert ci_alert.fetch_latest_run(urlopen=_raise(TimeoutError("slow"))) is None
    assert ci_alert.fetch_latest_run(urlopen=_raise(urllib.error.URLError("dns"))) is None
    assert ci_alert.fetch_latest_run(urlopen=_raise(
        urllib.error.HTTPError(ci_alert.GITEA_STATUS_URL, 500, "boom", {}, None))) is None
    assert ci_alert.fetch_latest_run(urlopen=_serve(b"not json")) is None
    assert ci_alert.fetch_latest_run(urlopen=_serve({"message": "not found"})) is None


def test_main_dry_run_prints_message_and_does_not_write_state(tmp_path, capsys):
    state_file = tmp_path / "state" / "ci-red-alert.json"
    run = {
        "databaseId": 999,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "dry run title",
        "url": "https://url",
    }
    ret = ci_alert.main(
        argv=["--dry-run"],
        repo_root=tmp_path,
        fetch_fn=lambda: run,
        now_fn=lambda: 1000,
    )
    assert ret == 0
    captured = capsys.readouterr()
    assert "failure: dry run title\nhttps://url" in captured.out
    assert not state_file.exists()


def test_main_send_failure_keeps_state_and_exits_1(tmp_path, capsys):
    state_file = tmp_path / "state" / "ci-red-alert.json"
    run = {
        "databaseId": 888,
        "conclusion": "failure",
        "status": "completed",
        "displayTitle": "fail title",
        "url": "https://url",
    }

    def failing_send(repo, msg):
        raise RuntimeError("network down")

    ret = ci_alert.main(
        argv=[],
        repo_root=tmp_path,
        fetch_fn=lambda: run,
        send_fn=failing_send,
        now_fn=lambda: 1000,
    )
    assert ret == 1
    captured = capsys.readouterr()
    assert "Error sending notification" in captured.err
    assert not state_file.exists()


class _Reply:
    def __init__(self, payload):
        self.payload = payload

    def read(self, *args):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _repo_with_env(tmp_path, monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text('export TELEGRAM_BOT_TOKEN="1:secret"\nTELEGRAM_CHAT_ID=2\nOTHER=x\n')
    return tmp_path


def test_send_reads_env_file_and_sends_plain_text_with_angle_brackets(tmp_path, monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["url"], seen["body"] = request.full_url, json.loads(request.data)
        return _Reply({"ok": True})

    ci_alert.send_notification(_repo_with_env(tmp_path, monkeypatch), "failure: fix <tag>", urlopen=urlopen)
    assert "1:secret" in seen["url"]
    assert seen["body"]["chat_id"] == "2"
    assert "<tag>" in seen["body"]["text"]
    assert "parse_mode" not in seen["body"]


def test_telegram_refusal_raises(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="refused"):
        ci_alert.send_notification(
            _repo_with_env(tmp_path, monkeypatch),
            "x",
            urlopen=lambda r, timeout: _Reply({"ok": False, "description": "bad"}),
        )


def test_network_error_never_prints_the_token(tmp_path, monkeypatch):
    def urlopen(request, timeout):
        raise OSError(f"failed {request.full_url}")

    with pytest.raises(RuntimeError) as err:
        ci_alert.send_notification(_repo_with_env(tmp_path, monkeypatch), "x", urlopen=urlopen)
    assert "secret" not in str(err.value)


def test_missing_credentials_raise(tmp_path, monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="missing"):
        ci_alert.send_notification(tmp_path, "x", urlopen=lambda r, timeout: _Reply({"ok": True}))


def test_cron_line_is_added_once_and_keeps_existing_jobs():
    once = ci_alert.with_cron_line("0 7 * * * other # keep\n", Path("/repo"))
    assert once.startswith("0 7 * * * other # keep\n")
    assert ci_alert.CRON_TAG in once and "/repo/scripts/ci_red_alert.py" in once
    assert ci_alert.with_cron_line(once, Path("/repo")) == once
