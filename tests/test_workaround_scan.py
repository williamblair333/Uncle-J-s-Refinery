import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
import importlib.util

_spec = importlib.util.spec_from_file_location("workaround_scan", REPO / "scripts" / "workaround_scan.py")
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)


@pytest.fixture(autouse=True)
def _temp_log(tmp_path, monkeypatch):
    # hits must never land in the real ~/.claude/state log
    monkeypatch.setattr(ws, "LOG", tmp_path / "scan.jsonl")
    monkeypatch.delenv("WORKAROUND_SCAN", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def say(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def transcript(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return {"transcript_path": str(p), "stop_hook_active": False, "cwd": "/x"}


@pytest.mark.parametrize("text", [
    "agy was denied git stash, so I worked around it by pasting the diff.",
    "I hand-fed agy the game data.",
    "Now waiting on the next dice roll to verify.",
    "I couldn't read the file, so I guessed the format.",
    "That's a workaround for now.",
    "As a workaround, I pasted the diff in.",
    "The workaround is to restart it by hand.",
    "Now waiting on agy's part 1.",
    "I'm waiting on the nightly run to confirm it.",
    "We're still waiting on the roll.",
])
def test_workaround_phrases_block(tmp_path, text):
    hook = transcript(tmp_path, [prompt("go"), say("Starting."), tool_result(), say(text)])
    out = ws.decide(hook)
    assert out and out["decision"] == "block" and "fix that cause" in out["reason"]


def test_main_logs_hit_without_content(tmp_path, monkeypatch, capsys):
    hook = transcript(tmp_path, [prompt("go"), say("I hand-fed agy the data.")])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(hook)))
    assert ws.main() == 0 and json.loads(capsys.readouterr().out)["decision"] == "block"
    rec = json.loads((tmp_path / "scan.jsonl").read_text())
    assert rec["hits"] == 1 and rec["cwd"] == "/x" and "hand" not in json.dumps(rec)


@pytest.mark.parametrize("text", ["Done: tests pass, PR #12 merged.", "I'm waiting on your answer.",
                                  "Still waiting on Bill to pick one.",
                                  # 2026-10-30 first live hits: naming the feature or the topic
                                  # is not routing around a block
                                  "I couldn't confirm the workaround-detector Stop hook is actually "
                                  "registered. Permissions blocked me from reading `~/.claude/settings.json`.",
                                  "Check `workaround-scan.jsonl` to see whether what the detector blocks "
                                  "are real workarounds.",
                                  "The workaround detector is live.",
                                  "Tune the workaround scan's phrases.",
                                  # 2026-10-31 bench (`just workaround-bench --days 3`) false hits
                                  "That wasn't a workaround. Permissions denied my read.",
                                  'The hook fires when a turn says "worked around", "hand-fed" or "waiting on X".',
                                  "Tell the user the push is waiting on it.",
                                  "- **Heretic:** waiting on llama.cpp #30528 before bumping.",
                                  "It's waiting on the last Heretic turn run in the SAGA layout.",
                                  # 2026-10-31 live hit: a table describing the check categories
                                  "| Hand-feeds a helper or works around a block | 1, then fix the access |",
                                  "agy reports one failure in the workaround tests.",
                                  "The workaround bench fired on 4.1% of turns."])
def test_clean_turn_passes(tmp_path, text):
    assert ws.decide(transcript(tmp_path, [prompt("go"), say(text)])) is None


def test_all_turns_splits_on_prompts_not_tool_results(tmp_path):
    hook = transcript(tmp_path, [prompt("a"), say("one."), tool_result(), say("two."),
                                 prompt("b"), say("three.")])
    turns = ws.all_turns(Path(hook["transcript_path"]))
    assert len(turns) == 2 and "one." in turns[0] and "two." in turns[0] and "three." in turns[1]


def test_replay_counts_fired_turns_and_never_logs(tmp_path):
    a = transcript(tmp_path, [prompt("a"), say("I hand-fed agy the data."), prompt("b"), say("Done.")])
    p2 = tmp_path / "t2.jsonl"
    p2.write_text(json.dumps(prompt("c")) + "\n" + json.dumps(say("The workaround detector is live.")) + "\n")
    r = ws.replay([Path(a["transcript_path"]), p2])
    assert r["turns"] == 3 and r["fired"] == 1 and len(r["hits"]) == 1
    assert r["hits"][0]["file"].endswith("t.jsonl") and "hand-fed" in r["hits"][0]["snippet"]
    assert not (tmp_path / "scan.jsonl").exists()


def test_replay_cli_prints_rate(tmp_path, capsys):
    a = transcript(tmp_path, [prompt("a"), say("I hand-fed agy the data."), prompt("b"), say("Done.")])
    assert ws.main(["--replay", "--files", a["transcript_path"]]) == 0
    out = capsys.readouterr().out
    assert "1/2 turns" in out and "50.0%" in out


def test_only_the_last_turn_is_scanned(tmp_path):
    hook = transcript(tmp_path, [prompt("a"), say("I worked around it."), prompt("b"), say("All fixed.")])
    assert ws.decide(hook) is None


def test_quoted_phrases_are_ignored(tmp_path):
    text = "The log says `agy worked around them`.\n> waiting on X\n```\nworkaround\n```\nNothing else."
    assert ws.decide(transcript(tmp_path, [prompt("go"), say(text)])) is None


def test_never_blocks_twice(tmp_path):
    hook = transcript(tmp_path, [prompt("go"), say("I worked around it.")])
    hook["stop_hook_active"] = True
    assert ws.decide(hook) is None


def test_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKAROUND_SCAN", "off")
    assert ws.decide(transcript(tmp_path, [prompt("go"), say("I worked around it.")])) is None


def test_headless_print_mode_is_skipped(tmp_path, monkeypatch):
    # claude -p callers (scout, dream, ralph, auto-maintain) parse the final message
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    assert ws.decide(transcript(tmp_path, [prompt("go"), say("I worked around it.")])) is None


def test_falls_back_to_last_assistant_message(tmp_path):
    hook = {"transcript_path": str(tmp_path / "missing.jsonl"), "last_assistant_message": "hand-fed it"}
    assert ws.decide(hook)["decision"] == "block"


def test_reads_only_the_tail_of_a_large_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "TAIL_BYTES", 400)
    filler = [say("x" * 50) for _ in range(40)]
    hook = transcript(tmp_path, [prompt("old"), say("I worked around it.")] + filler + [say("still waiting on CI")])
    assert "waiting on" in ws.decide(hook)["reason"]


def test_hook_script_fails_open_and_emits_json(tmp_path):
    sh = REPO / "hooks" / "discipline" / "workaround-scan.sh"
    hook = transcript(tmp_path, [prompt("go"), say("I hand-fed agy the data.")])
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_CODE_ENTRYPOINT": "cli"}
    r = subprocess.run(["bash", str(sh)], input=json.dumps(hook), capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["decision"] == "block"
    r = subprocess.run(["bash", str(sh)], input="not json", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""
