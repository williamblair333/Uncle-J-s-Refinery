"""scripts/chance_check.py: a turn that leaves proof to chance gets one forced look at forcing it."""
import http.server
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "chance_check.py"
HOOK = REPO / "hooks" / "discipline" / "chance-check.sh"
_spec = importlib.util.spec_from_file_location("chance_check", SCRIPT)
cc = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(REPO / "scripts"))
_spec.loader.exec_module(cc)

LONG = "The fix is merged and the unit tests pass. " * 12
FLAG = {"kind": cc.FORCEABLE, "quote": "the unit tests pass", "event": "a wife offer on a fresh turn",
        "how_to_force": "call marryWife from EOP"}
CLEAR = {"kind": "no_gap", "quote": "", "event": "none", "how_to_force": "none"}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "LOG", tmp_path / "chance.jsonl")
    for k in ("CHANCE_CHECK", "CHANCE_CHECK_URL", "CHANCE_CHECK_LOG", "HOOK_BENCH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")


def must_not_call(*a, **k):
    raise AssertionError("the model must not be called")


def test_a_flag_blocks_with_the_event_and_the_idea():
    v = cc.decide({"last_assistant_message": LONG}, ask=lambda *a: FLAG)
    assert v["decision"] == "block"
    assert "a wife offer on a fresh turn" in v["reason"] and "marryWife" in v["reason"]


def test_the_reason_requires_the_step_and_keeps_the_way_out():
    r = cc.decide({"last_assistant_message": LONG}, ask=lambda *a: FLAG)["reason"]
    assert "slowest-loop-first" in r and "repeatable" in r
    assert "real code path" in r and "never fake" in r     # caliper readings, 2026-11-06
    assert "one line" in r                                  # "not worth forcing, because…"


def test_clear_verdict_passes():
    assert cc.decide({"last_assistant_message": LONG}, ask=lambda *a: CLEAR) is None


@pytest.mark.parametrize("verdict", [None, {}, {"kind": 1}, ["x"], "yes", {"kind": cc.FORCEABLE}])
def test_a_malformed_verdict_passes(verdict):
    assert cc.decide({"last_assistant_message": LONG}, ask=lambda *a: verdict) is None


@pytest.mark.parametrize("kind", [k for k in cc.KINDS if k != cc.FORCEABLE])
def test_every_other_kind_passes(kind):
    assert cc.decide({"last_assistant_message": LONG}, ask=lambda *a: {**FLAG, "kind": kind}) is None


@pytest.mark.parametrize("quote", ["a gap the model imagined entirely", "", "tests", 123, None])
def test_a_quote_that_is_not_in_the_message_passes(quote):
    assert cc.decide({"last_assistant_message": LONG}, ask=lambda *a: {**FLAG, "quote": quote}) is None


def test_a_quote_matches_across_case_and_line_breaks():
    text = LONG + "\nThe Offer path\n  hasn't run yet."
    v = {**FLAG, "quote": "the offer path hasn't run yet"}
    assert cc.decide({"last_assistant_message": text}, ask=lambda *a: v)


def test_model_failure_fails_open_and_is_logged():
    def boom(*a):
        raise OSError("connection refused")
    assert cc.decide({"last_assistant_message": LONG}, ask=boom) is None
    row = json.loads(cc.LOG.read_text().splitlines()[-1])
    assert row["ok"] is False and "seconds" in row


def test_log_holds_no_reply_text():
    cc.decide({"last_assistant_message": LONG}, ask=lambda *a: FLAG)
    logged = cc.LOG.read_text()
    assert "unit tests" not in logged and "marryWife" not in logged and "wife" not in logged


def test_short_replies_skip_the_model():
    assert cc.decide({"last_assistant_message": "Fixed."}, ask=must_not_call) is None


@pytest.mark.parametrize("bad", [123, ["x"], {"a": 1}, True, None])
def test_a_non_string_message_never_crashes(bad):
    assert cc.decide({"last_assistant_message": bad}, ask=must_not_call) is None


def test_blocks_only_once():
    assert cc.decide({"last_assistant_message": LONG, "stop_hook_active": True}, ask=must_not_call) is None


def test_kill_switch_headless_and_hook_bench(monkeypatch):
    hook = {"last_assistant_message": LONG}
    monkeypatch.setenv("CHANCE_CHECK", "off")
    assert cc.decide(hook, ask=must_not_call) is None
    monkeypatch.delenv("CHANCE_CHECK")
    monkeypatch.setenv("HOOK_BENCH", "1")           # the replay bench must not call the model thousands of times
    assert cc.decide(hook, ask=must_not_call) is None
    monkeypatch.delenv("HOOK_BENCH")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert cc.decide(hook, ask=must_not_call) is None


# Text-leaving-the-machine: the risk Bill accepted by name, on the condition this holds.
@pytest.mark.parametrize("url", [
    "http://10.0.0.100:8090", "https://api.example.com", "http://127.0.0.1.evil.com:8090",
    "http://localhost@evil.com/", "http://127.0.0.1:8090@evil.com/", "ftp://127.0.0.1:8090", "not a url", "",
])
def test_anything_but_a_loopback_address_is_refused(url, monkeypatch):
    monkeypatch.setenv("CHANCE_CHECK_URL", url)
    assert not cc.is_local(url)
    assert cc.decide({"last_assistant_message": LONG}, ask=must_not_call) is None


@pytest.mark.parametrize("url", ["http://127.0.0.1:8090", "http://localhost:8090", "http://[::1]:8090"])
def test_loopback_addresses_are_allowed(url):
    assert cc.is_local(url)


class _Fake(http.server.BaseHTTPRequestHandler):
    reply = json.dumps(FLAG)
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Fake.seen.append(body)
        out = json.dumps({"choices": [{"message": {"content": _Fake.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Fake.seen = []
    s = http.server.HTTPServer(("127.0.0.1", 0), _Fake)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run(stdin, tmp_path, **env):
    full = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_CODE_ENTRYPOINT": "cli",
            "CHANCE_CHECK_LOG": str(tmp_path / "log.jsonl"), **env}
    return subprocess.run(["bash", str(HOOK)], input=stdin, capture_output=True, text=True, env=full)


def test_hook_script_blocks_on_a_flag_with_thinking_off(server, tmp_path):
    r = _run(json.dumps({"last_assistant_message": LONG}), tmp_path, CHANCE_CHECK_URL=server)
    assert r.returncode == 0 and json.loads(r.stdout)["decision"] == "block"
    assert _Fake.seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert _Fake.seen[0]["temperature"] == 0


def test_a_proxy_setting_cannot_carry_the_text_off_the_machine(server, tmp_path):
    dead = f"http://127.0.0.1:{_free_port()}"
    r = _run(json.dumps({"last_assistant_message": LONG}), tmp_path, CHANCE_CHECK_URL=server,
             http_proxy=dead, HTTP_PROXY=dead, all_proxy=dead, ALL_PROXY=dead, no_proxy="", NO_PROXY="")
    assert json.loads(r.stdout)["decision"] == "block"     # reached the local server, not the proxy
    assert len(_Fake.seen) == 1


def test_only_the_tail_of_a_long_message_is_sent(server, tmp_path):
    _run(json.dumps({"last_assistant_message": "x" * 9000 + LONG}), tmp_path, CHANCE_CHECK_URL=server)
    assert len(_Fake.seen[0]["messages"][-1]["content"]) <= 2500


def test_hook_script_fails_open(tmp_path):
    down = f"http://127.0.0.1:{_free_port()}"
    for stdin in (json.dumps({"last_assistant_message": LONG}), "not json", "[1,2]"):
        r = _run(stdin, tmp_path, CHANCE_CHECK_URL=down)
        assert r.returncode == 0 and r.stdout == ""


def test_prose_around_the_json_still_parses():
    assert cc.parse('Here you go:\n{"kind": "no_gap", "event": "x"}\nDone.')["event"] == "x"
    assert cc.parse("no json here") is None
    assert cc.parse('{"kind": "no_g') is None


def test_bench_cases_are_labelled_and_cover_both_ways():
    cases = cc.load_cases(REPO / "bench" / "chance-cases.jsonl")
    labels = [c["waiting"] for c in cases]
    assert all(isinstance(x, bool) for x in labels) and labels.count(True) >= 5 and labels.count(False) >= 5
    assert all(len(c["text"]) >= cc.MIN_CHARS for c in cases)    # or the hook would never read them


def test_bench_scores_a_fake_model(tmp_path):
    a_text, b_text = "the first message here", "the second message here"
    cases = [{"id": "a", "waiting": True, "text": a_text}, {"id": "b", "waiting": False, "text": b_text}]
    r = cc.score(cases, lambda text, *a: {"kind": cc.FORCEABLE if text == b_text else "no_gap", "quote": text})
    assert r["missed"] == ["a"] and r["wrong_flags"] == ["b"]
    assert os.path.exists(REPO / "justfile")
