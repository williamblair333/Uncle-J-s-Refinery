"""hook_bench: settings parsing, event extraction, fire classification, sandboxing."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import hook_bench as hb  # noqa: E402

CFG = {"skip": ["jcodemunch-mcp"], "live_state": {"pr-check.sh": "reads PRs"},
       "leaks_state": {"token-guard.sh": "hardcoded log"},
       "names": {"rm\\s+-": "rm-guard"}}


def _settings(tmp_path, hooks):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": hooks}))
    return [("global", p)]


def test_load_hooks_statuses_and_names(tmp_path):
    s = _settings(tmp_path, {
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"command": "bash ~/.claude/hooks/discipline/grep-guard.sh"},
            {"command": "x=$(cat); echo \"$x\" | grep -q 'rm\\s+-' && exit 2  # "},
            {"command": "jcodemunch-mcp hook-pretooluse"},
            {"command": "bash ~/.claude/hooks/pre-mortem-guard/token-guard.sh"}]}],
        "Stop": [{"hooks": [{"command": "bash pr-check.sh"},
                            {"command": "bash /x/force-rules.sh  # uncle-j-force-rules"}]}],
        "SessionStart": [{"hooks": [{"command": "bash start.sh"}]}],
    })
    hooks = {h["name"]: h for h in hb.load_hooks(CFG, s)}
    assert hooks["grep-guard.sh"]["status"] == "run"
    assert hooks["grep-guard.sh"]["matcher"] == "Bash"
    assert hooks["rm-guard"]["status"] == "run"
    assert hooks["uncle-j-force-rules"]["status"] == "run"
    assert hooks["pr-check.sh"]["status"] == "live_state"
    assert hooks["token-guard.sh"]["status"] == "leaks_state"
    assert hooks["start.sh"]["status"] == "not_replayed"
    assert [h for h in hooks.values() if "jcodemunch" in h["command"]][0]["status"] == "skip"


@pytest.mark.parametrize("event,rc,out,err,want", [
    ("PreToolUse", 2, "", "BLOCKED: no", ("block", "BLOCKED: no")),
    ("PreToolUse", 0, json.dumps({"hookSpecificOutput": {"permissionDecision": "deny",
                                  "permissionDecisionReason": "offload"}}), "", ("block", "offload")),
    ("Stop", 0, json.dumps({"decision": "block", "reason": "check"}), "", ("block", "check")),
    ("UserPromptSubmit", 0, "use skill X", "", ("inject", "use skill X")),
    ("PreToolUse", 0, "chatter", "", ("pass", "")),
    ("PreToolUse", 0, "", "", ("pass", "")),
    ("Stop", 1, "", "Traceback", ("error", "Traceback")),
])
def test_classify(event, rc, out, err, want):
    assert hb.classify(event, rc, out, err) == want


def _entry(kind, content, **kw):
    return {"type": kind, "sessionId": "s1", "cwd": str(REPO),
            "timestamp": "2099-01-01T00:00:00Z", "message": {"content": content}, **kw}


def _transcript(tmp_path):
    lines = [
        _entry("user", "first prompt"),
        _entry("assistant", [{"type": "text", "text": "looking"},
                             {"type": "tool_use", "id": "t1", "name": "Bash",
                              "input": {"command": "grep x scripts/a.py"}}]),
        _entry("user", [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                         "content": "PreToolUse:Bash hook error: Reading/searching repo source via shell is blocked"}]),
        _entry("assistant", [{"type": "text", "text": "done"}]),
        _entry("user", "<task-notification>agent finished</task-notification>"),
        _entry("assistant", [{"type": "text", "text": "noted"}], isSidechain=True),
        _entry("user", "second prompt"),
        _entry("assistant", [{"type": "text", "text": "ok"}]),
    ]
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    return p


def test_events_from_transcript(tmp_path):
    evs = hb.events_from(_transcript(tmp_path), since=0)
    assert [e["event"] for e in evs] == ["UserPromptSubmit", "PreToolUse", "Stop",
                                         "UserPromptSubmit", "Stop"]
    assert evs[1]["tool"] == "Bash"
    assert evs[1]["live"].startswith("Reading/searching repo source")
    assert evs[2]["text"] == "looking\ndone"   # task notification does not split the turn
    assert evs[4]["text"] == "ok"


def test_events_respect_since(tmp_path):
    assert hb.events_from(_transcript(tmp_path), since=4102444800 + 10) == []


def test_bench_hook_counts_fires_and_live_agreement(tmp_path):
    box, env = hb.make_sandbox()
    try:
        hook = {"name": "fake", "event": "PreToolUse", "matcher": "Bash", "scope": "global",
                "command": "grep -q BAD && { echo 'blocked: bad thing here' >&2; exit 2; }; exit 0"}
        mk = lambda cmd, live=None: {"event": "PreToolUse", "session": "s", "cwd": str(tmp_path),
                                     "tool": "Bash", "input": {"command": cmd}, "live": live}
        evs = [mk("BAD one", live="blocked: bad thing here"),  # agrees with live
               mk("BAD two"),                                  # new behaviour
               mk("fine", live="blocked: bad thing here"),     # live blocked, replay doesn't
               mk("fine")]
        res = hb.bench_hook(hook, evs, env)
    finally:
        import shutil
        shutil.rmtree(box)
    assert res["events"] == 4 and len(res["fires"]) == 2
    assert res["replay_only"] == 1 and res["live_only"] == 1
    assert not res["errors"]


def test_applies_scope_and_matcher():
    proj = {"event": "PreToolUse", "matcher": "Edit|Write", "scope": "project"}
    ev = {"event": "PreToolUse", "tool": "Write", "cwd": str(REPO)}
    assert hb.applies(proj, ev)
    assert not hb.applies(proj, {**ev, "cwd": "/elsewhere"})
    assert not hb.applies(proj, {**ev, "tool": "Read"})
    assert hb.applies({**proj, "matcher": "*", "scope": "global"}, {**ev, "tool": "Read", "cwd": "/x"})


def test_sandbox_removal_never_follows_home_symlinks(tmp_path):
    """The sandbox mirrors HOME with symlinks; removing it must unlink them, not recurse."""
    import shutil
    real = tmp_path / "realhome" / "keep"
    real.mkdir(parents=True)
    (real / "file.txt").write_text("x")
    box = tmp_path / "box"
    (box / ".claude").mkdir(parents=True)
    (box / "keep").symlink_to(real)
    (box / ".claude" / "hooks").symlink_to(real)
    shutil.rmtree(box, ignore_errors=True)
    assert not box.exists()
    assert (real / "file.txt").read_text() == "x"


def test_sandbox_mirrors_home_except_state():
    box, env = hb.make_sandbox()
    try:
        assert env["HOME"] == str(box)
        assert (box / ".claude" / "state").is_dir() and not (box / ".claude" / "state").is_symlink()
        assert (box / ".claude" / "projects").is_symlink() == (Path.home() / ".claude" / "projects").exists()
    finally:
        import shutil
        shutil.rmtree(box)
    assert (Path.home() / ".claude").is_dir()


def test_labels_roundtrip_and_precision(tmp_path):
    lab = tmp_path / "labels.jsonl"
    hb.add_label("k1", "false", "reads transcripts", lab)
    hb.add_label("k2", "true", "", lab)
    labels = hb.load_labels(lab)
    res = {"events": 10, "errors": __import__("collections").Counter(), "replay_only": 0,
           "live_only": 0, "fires": [
               {"key": k, "verdict": "block", "message": "m",
                "event": {"event": "Stop", "text": "t"}} for k in ("k1", "k2", "k3")]}
    row = hb.summarise({"name": "h", "event": "Stop", "scope": "global"}, res, labels)
    assert (row["fires"], row["labelled"], row["false"], row["precision"]) == (3, 2, 1, 0.5)
    assert [u["key"] for u in row["unlabelled"]] == ["k3"]
    with pytest.raises(SystemExit):
        hb.add_label("k", "maybe", "", lab)


@pytest.mark.parametrize("name,command,bash_cmd", [
    ("grep-guard.sh", f"bash {REPO / 'hooks/discipline/grep-guard.sh'}",
     "grep -n def scripts/hook_bench.py"),
    # dcup_guard wrote bench- lines into the real log until it honoured UNCLE_J_PROJ_ROOT (10-31)
    ("dcup:guard", f"python3 {REPO / 'features/dcup/dcup_guard.py'}",
     "docker run -d -p 8123:80 nginx"),
])
def test_real_guard_in_sandbox_does_not_touch_block_log(name, command, bash_cmd):
    """The pre-mortem mitigation: replaying a blocking guard must not append to the real log."""
    log = REPO / "state" / "hook-blocks.log"
    before = log.stat().st_size if log.exists() else None
    box, env = hb.make_sandbox()
    try:
        hook = {"name": name, "event": "PreToolUse", "matcher": "Bash",
                "scope": "global", "command": command}
        ev = {"event": "PreToolUse", "session": "s", "cwd": str(REPO), "tool": "Bash",
              "input": {"command": bash_cmd}, "live": None}
        verdict, _ = hb.run_one(hook, ev, env)
    finally:
        import shutil
        shutil.rmtree(box)
    assert verdict == "block"
    assert (log.stat().st_size if log.exists() else None) == before
