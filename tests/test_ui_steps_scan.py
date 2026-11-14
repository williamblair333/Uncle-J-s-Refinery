import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
_spec = importlib.util.spec_from_file_location("ui_steps_scan", REPO / "scripts" / "ui_steps_scan.py")
us = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(us)

STALE = ("1. Go to https://console.cloud.google.com/auth/overview\n"
         "2. Click **Get started**.\n3. Fill in the app name, then click **Save**.")


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "LOG", tmp_path / "scan.jsonl")
    monkeypatch.delenv("UI_STEPS_SCAN", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def say(text, tools=()):
    content = [{"type": "text", "text": text}]
    content += [{"type": "tool_use", "name": t, "input": {}} for t in tools]
    return {"type": "assistant", "message": {"content": content}}


def hook(tmp_path, entries, active=False):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return {"transcript_path": str(p), "stop_hook_active": active, "cwd": "/x"}


def test_stale_gui_only_steps_block_on_both_rules(tmp_path):
    v = us.decide(hook(tmp_path, [prompt("set up oauth"), say(STALE)]))
    assert v and v["missing"] == ["fresh", "cli"]


def test_fetched_and_cli_given_passes(tmp_path):
    text = STALE + "\nCLI: `gcloud iam oauth-clients create ...`"
    assert us.decide(hook(tmp_path, [prompt("x"), say(text, ["WebFetch"])])) is None


def test_from_memory_label_satisfies_freshness_only(tmp_path):
    v = us.decide(hook(tmp_path, [prompt("x"), say(STALE + "\n(from memory, may be out of date)")]))
    assert v["missing"] == ["cli"]


def test_no_cli_exists_statement_passes_cli_rule(tmp_path):
    text = STALE + "\nNo CLI exists for this; a script could call the REST API."
    assert us.decide(hook(tmp_path, [prompt("x"), say(text, ["WebSearch"])])) is None


def test_fetch_in_an_earlier_turn_does_not_count(tmp_path):
    v = us.decide(hook(tmp_path, [prompt("a"), say("looked", ["WebFetch"]), prompt("b"), say(STALE)]))
    assert "fresh" in v["missing"]


@pytest.mark.parametrize("text", [
    "Paste the command and press Enter, then press Enter again.",
    "Checking the Gitea → GitHub mirror and the MCP → CLI → MCP wrapping.",
    "```\nclick **Save**\nclick **Done**\n```",
    "Click **Save**.",  # one hit is not a set of steps
])
def test_not_vendor_steps(tmp_path, text):
    assert us.decide(hook(tmp_path, [prompt("x"), say(text)])) is None


def test_own_local_page_needs_cli_but_not_a_lookup(tmp_path):
    text = "Open http://127.0.0.1:8091 and click Send, then click Stop."
    assert us.decide(hook(tmp_path, [prompt("x"), say(text)]))["missing"] == ["cli"]


def test_menu_path_counts(tmp_path):
    text = "Go to **Settings → Devices & services → Helpers**, then click **Create helper**."
    assert us.decide(hook(tmp_path, [prompt("x"), say(text)]))


def test_never_blocks_twice_or_in_sdk_or_when_off(tmp_path, monkeypatch):
    entries = [prompt("x"), say(STALE)]
    assert us.decide(hook(tmp_path, entries, active=True)) is None
    monkeypatch.setenv("UI_STEPS_SCAN", "off")
    assert us.decide(hook(tmp_path, entries)) is None
    monkeypatch.delenv("UI_STEPS_SCAN")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert us.decide(hook(tmp_path, entries)) is None


def test_hook_script_fails_open_and_emits_json(tmp_path):
    sh = REPO / "hooks" / "discipline" / "ui-steps-scan.sh"
    h = hook(tmp_path, [prompt("x"), say(STALE)])
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_CODE_ENTRYPOINT": "cli"}
    r = subprocess.run(["bash", str(sh)], input=json.dumps(h), capture_output=True, text=True, env=env)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["decision"] == "block" and "missing" not in out
    r = subprocess.run(["bash", str(sh)], input="not json", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""
