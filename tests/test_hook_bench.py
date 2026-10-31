"""hook_bench: settings parsing, event extraction, fire classification, sandboxing."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import hook_bench as hb  # noqa: E402

CFG = {"skip": ["jcodemunch-mcp"], "live_state": {"pr-check.sh": "reads PRs"},
       "leaks_state": {"token-guard.sh": "hardcoded log"},
       "names": {"rm\\s+-": "rm-guard"}}


def test_export_dest_must_be_ignored_or_outside_repo(tmp_path):
    """The bundle holds transcript text: never somewhere git would commit it."""
    assert hb.export_dest_ok(REPO / "state" / "hook-bench-export")      # gitignored
    assert hb.export_dest_ok(tmp_path / "bundle")                       # outside the repo
    assert not hb.export_dest_ok(REPO / "bench" / "bundle")             # tracked dir
    with pytest.raises(SystemExit):
        hb.main(["--export", str(REPO / "bench" / "bundle")])
    assert not (REPO / "bench" / "bundle").exists()


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
    had_claude = (Path.home() / ".claude").is_dir()
    box, env = hb.make_sandbox()
    try:
        assert env["HOME"] == str(box)
        assert (box / ".claude" / "state").is_dir() and not (box / ".claude" / "state").is_symlink()
        assert (box / ".claude" / "projects").is_symlink() == (Path.home() / ".claude" / "projects").exists()
    finally:
        import shutil
        shutil.rmtree(box)
    assert (Path.home() / ".claude").is_dir() == had_claude   # removal left HOME as it was


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


def test_export_and_from_roundtrip(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    proj_dir = tmp_path / "projects" / "test_proj"
    proj_dir.mkdir(parents=True)
    transcript_file = proj_dir / "t.jsonl"
    lines = [
        _entry("user", "first prompt"),
        _entry("assistant", [{"type": "text", "text": "looking"},
                             {"type": "tool_use", "id": "t1", "name": "Bash",
                              "input": {"command": "grep BAD scripts/a.py"}}]),
        _entry("user", [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                         "content": "PreToolUse:Bash hook error: bad command"}]),
        _entry("assistant", [{"type": "text", "text": "done"}]),
    ]
    transcript_file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    settings_file = tmp_path / "settings.json"
    hook_cmd = "grep -q BAD && { echo 'bad command' >&2; exit 2; }; exit 0"
    settings_file.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [{"command": hook_cmd}]
            }]
        }
    }))

    settings = [("global", settings_file)]
    cfg = {"skip": [], "live_state": {}, "leaks_state": {}, "names": {}}

    # Direct run
    direct_events = hb.collect_events(days=7, root=tmp_path / "projects")
    direct_hooks = [h for h in hb.load_hooks(cfg, settings=settings) if h["status"] == "run"]
    box1, env1 = hb.make_sandbox()
    try:
        direct_rows = [hb.summarise(h, hb.bench_hook(h, [e for e in direct_events if hb.applies(h, e)], env1), {}) for h in direct_hooks]
    finally:
        shutil.rmtree(box1, ignore_errors=True)

    # Export bundle
    export_dir = tmp_path / "bundle"
    hb.export_bundle(export_dir, days=7, cfg=cfg, settings=settings, projects_root=tmp_path / "projects")

    # From bundle run
    bundle_settings = hb.load_bundle_settings(export_dir)
    bundle_events = hb.load_events(export_dir / "events.jsonl")
    bundle_hooks = [h for h in hb.load_hooks(cfg, settings=bundle_settings) if h["status"] == "run"]
    box2, env2 = hb.make_sandbox()
    try:
        bundle_rows = [hb.summarise(h, hb.bench_hook(h, [e for e in bundle_events if hb.applies(h, e)], env2), {}) for h in bundle_hooks]
    finally:
        shutil.rmtree(box2, ignore_errors=True)

    assert bundle_rows == direct_rows
    assert len(bundle_rows) == 1
    assert bundle_rows[0]["fires"] == 1

    # CLI export with monkeypatched paths to avoid reading real ~/.claude
    cli_export = tmp_path / "cli_bundle"
    monkeypatch.setattr(hb, "SETTINGS", settings)
    monkeypatch.setattr(hb, "PROJECTS", tmp_path / "projects")
    assert hb.main(["--export", str(cli_export)]) == 0
    assert (cli_export / "events.jsonl").exists()
    assert (cli_export / "settings-global.json").exists()

    # --hook filter on export
    filtered_export = tmp_path / "filtered_bundle"
    hb.export_bundle(filtered_export, days=7, hook_filter="nonexistent", cfg=cfg, settings=settings, projects_root=tmp_path / "projects")
    filtered_settings = json.loads((filtered_export / "settings-global.json").read_text())
    assert filtered_settings["hooks"] == {}


def test_command_rewrite_symlink(tmp_path):
    fake_home = tmp_path / "fake_home"
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    hooks_dir = fake_home / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)

    # 1. Symlink pointing into fake_repo
    target = fake_repo / "discipline" / "guard.sh"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/bash\nexit 0\n")
    symlink_inside = hooks_dir / "guard.sh"
    symlink_inside.symlink_to(target)

    # 2. Non-symlink inside fake_home/.claude/hooks
    regular = hooks_dir / "regular.sh"
    regular.write_text("#!/bin/bash\nexit 0\n")

    # 3. Symlink pointing outside fake_repo
    outside_target = tmp_path / "outside.sh"
    outside_target.write_text("#!/bin/bash\nexit 0\n")
    symlink_outside = hooks_dir / "outside.sh"
    symlink_outside.symlink_to(outside_target)

    # A symlink in a fake home's .claude/hooks pointing into a fake repo dir is rewritten
    cmd_tilde = "bash ~/.claude/hooks/guard.sh"
    assert hb.rewrite_command(cmd_tilde, repo=fake_repo, home=fake_home) == f"bash {target.resolve()}"

    cmd_dollar = "bash $HOME/.claude/hooks/guard.sh"
    assert hb.rewrite_command(cmd_dollar, repo=fake_repo, home=fake_home) == f"bash {target.resolve()}"

    cmd_full = f"bash {fake_home}/.claude/hooks/guard.sh"
    assert hb.rewrite_command(cmd_full, repo=fake_repo, home=fake_home) == f"bash {target.resolve()}"

    # A non-symlink is not rewritten without bundle
    cmd_reg = "bash ~/.claude/hooks/regular.sh"
    assert hb.rewrite_command(cmd_reg, repo=fake_repo, home=fake_home) == cmd_reg

    # A path outside the repo is not rewritten without bundle
    cmd_out = "bash ~/.claude/hooks/outside.sh"
    assert hb.rewrite_command(cmd_out, repo=fake_repo, home=fake_home) == cmd_out

    # When bundle is provided, real file and outside symlink are copied and rewritten
    bundle_cmd = tmp_path / "bundle_cmd"
    assert hb.rewrite_command(cmd_reg, repo=fake_repo, home=fake_home, bundle=bundle_cmd) == f"bash {(bundle_cmd / 'hooks' / 'regular.sh').resolve()}"
    assert (bundle_cmd / "hooks" / "regular.sh").is_file()

    assert hb.rewrite_command(cmd_out, repo=fake_repo, home=fake_home, bundle=bundle_cmd) == f"bash {(bundle_cmd / 'hooks' / 'outside.sh').resolve()}"
    assert (bundle_cmd / "hooks" / "outside.sh").is_file()

    # Unrelated command remains untouched
    cmd_other = "grep -q BAD && exit 2"
    assert hb.rewrite_command(cmd_other, repo=fake_repo, home=fake_home) == cmd_other


def test_from_works_with_empty_home(tmp_path, monkeypatch, capsys):
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))

    export_dir = tmp_path / "bundle"
    export_dir.mkdir()
    ev = {"event": "PreToolUse", "session": "s1", "cwd": str(REPO),
          "tool": "Bash", "input": {"command": "echo BAD"}, "live": None}
    (export_dir / "events.jsonl").write_text(json.dumps(ev) + "\n")
    (export_dir / "settings-global.json").write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [{"command": "grep -q BAD && { echo 'blocked' >&2; exit 2; }; exit 0"}]
            }]
        }
    }))

    rc = hb.main(["--from", str(export_dir), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data["hooks"]) == 1
    assert data["hooks"][0]["fires"] == 1
    assert not (empty_home / ".claude").exists()


def test_real_file_hook_copied_rewritten_and_runs(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake_home"
    fake_repo = tmp_path / "fake_repo"
    fake_repo.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    hook_dir = fake_home / ".claude" / "hooks" / "scan-commit"
    hook_dir.mkdir(parents=True)
    helper = hook_dir / "helper.sh"
    helper.write_text("MSG='blocked by scan-commit'\n")
    script = hook_dir / "scan-commit.sh"
    script.write_text("""#!/bin/bash
source "$(dirname "$0")/helper.sh"
echo "$MSG" >&2
exit 2
""")
    script.chmod(0o755)

    single = fake_home / ".claude" / "hooks" / "single.sh"
    single.write_text("#!/bin/bash\nexit 0\n")
    single.chmod(0o755)

    bundle_dir = tmp_path / "bundle"

    # rewrite_command copies directory and preserves siblings
    cmd_dir = "bash ~/.claude/hooks/scan-commit/scan-commit.sh"
    rewritten_dir = hb.rewrite_command(cmd_dir, repo=fake_repo, home=fake_home, bundle=bundle_dir)
    expected_copy = (bundle_dir / "hooks" / "scan-commit" / "scan-commit.sh").resolve()
    assert rewritten_dir == f"bash {expected_copy}"
    assert expected_copy.is_file()
    assert (bundle_dir / "hooks" / "scan-commit" / "helper.sh").is_file()

    # Full export bundle with real-file hook
    proj_dir = tmp_path / "projects" / "test_proj"
    proj_dir.mkdir(parents=True)
    transcript_file = proj_dir / "t.jsonl"
    lines = [
        _entry("user", "run git"),
        _entry("assistant", [{"type": "tool_use", "id": "t1", "name": "Bash",
                              "input": {"command": "git commit -m test"}}]),
        _entry("user", [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                         "content": "PreToolUse:Bash hook error: blocked"}]),
        _entry("assistant", [{"type": "text", "text": "done"}]),
    ]
    transcript_file.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    settings_file = fake_home / "settings.json"
    settings_file.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [{
                "matcher": "Bash",
                "hooks": [{"command": "bash ~/.claude/hooks/scan-commit/scan-commit.sh"}]
            }]
        }
    }))

    export_dest = tmp_path / "full_bundle"
    hb.export_bundle(export_dest, days=7, cfg={"skip": [], "live_state": {}, "leaks_state": {}, "names": {}},
                     settings=[("global", settings_file)], projects_root=tmp_path / "projects",
                     repo=fake_repo, home=fake_home)

    # Empty home for --from replay
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))

    bundle_settings = hb.load_bundle_settings(export_dest)
    bundle_events = hb.load_events(export_dest / "events.jsonl")
    bundle_hooks = [h for h in hb.load_hooks({"skip": [], "live_state": {}, "leaks_state": {}, "names": {}},
                                            settings=bundle_settings) if h["status"] == "run"]
    assert len(bundle_hooks) == 1
    assert str((export_dest / "hooks" / "scan-commit" / "scan-commit.sh").resolve()) in bundle_hooks[0]["command"]

    box, env = hb.make_sandbox(bundle=export_dest)
    try:
        matching = [e for e in bundle_events if hb.applies(bundle_hooks[0], e)]
        res = hb.bench_hook(bundle_hooks[0], matching, env)
        assert len(res["fires"]) == 1
        assert res["fires"][0]["verdict"] == "block"
        assert "blocked by scan-commit" in res["fires"][0]["message"]
        assert sum(res["errors"].values()) == 0
    finally:
        shutil.rmtree(box, ignore_errors=True)


def test_skills_stub_dir_in_sandbox_under_from(tmp_path, monkeypatch):
    fake_home = tmp_path / "fake_home"
    skills_dir = fake_home / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))

    skill1 = skills_dir / "alpha-skill"
    skill1.mkdir()
    (skill1 / "SKILL.md").write_text("# Alpha Skill\nShould not be copied.\n")

    outside_skill = tmp_path / "outside_skills" / "beta-skill"
    outside_skill.mkdir(parents=True)
    (outside_skill / "SKILL.md").write_text("# Beta Skill\nShould not be copied.\n")
    skill2 = skills_dir / "beta-skill"
    skill2.symlink_to(outside_skill)

    not_skill = skills_dir / "gamma-dir"
    not_skill.mkdir()
    (not_skill / "README.md").write_text("Not a skill")

    bundle_dir = tmp_path / "bundle"
    hb.export_bundle(bundle_dir, cfg={}, settings=[], projects_root=tmp_path, home=fake_home)

    stub1 = bundle_dir / "skills" / "alpha-skill" / "SKILL.md"
    assert stub1.is_file()
    assert stub1.stat().st_size == 0

    stub2 = bundle_dir / "skills" / "beta-skill" / "SKILL.md"
    assert stub2.is_file()
    assert stub2.stat().st_size == 0

    assert not (bundle_dir / "skills" / "gamma-dir").exists()

    # Sandbox under --from with empty HOME
    empty_home = tmp_path / "empty_home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))

    box, env = hb.make_sandbox(bundle=bundle_dir)
    try:
        sandbox_skills = box / ".claude" / "skills"
        assert sandbox_skills.is_symlink()
        assert sandbox_skills.resolve() == (bundle_dir / "skills").resolve()
        assert (sandbox_skills / "alpha-skill" / "SKILL.md").is_file()
        assert (sandbox_skills / "beta-skill" / "SKILL.md").is_file()
        assert not (sandbox_skills / "gamma-dir").exists()

        # skill_name_trigger runs inside sandbox env and detects stub skill
        trigger_script = hb.REPO / "features" / "prompt-triggers" / "skill_name_trigger.py"
        p = subprocess.run([sys.executable, str(trigger_script)],
                           input=json.dumps({"prompt": "please run alpha-skill now"}),
                           capture_output=True, text=True, env=env)
        out = json.loads(p.stdout)
        assert "alpha-skill" in out["hookSpecificOutput"]["additionalContext"]
    finally:
        shutil.rmtree(box, ignore_errors=True)

    # Sandbox under --from replacing any mirrored skills
    dirty_home = tmp_path / "dirty_home"
    dirty_skills = dirty_home / ".claude" / "skills"
    dirty_skills.mkdir(parents=True)
    (dirty_skills / "old-skill").mkdir()
    (dirty_skills / "old-skill" / "SKILL.md").write_text("old")
    monkeypatch.setenv("HOME", str(dirty_home))

    box2, env2 = hb.make_sandbox(bundle=bundle_dir)
    try:
        sandbox_skills = box2 / ".claude" / "skills"
        assert sandbox_skills.is_symlink()
        assert sandbox_skills.resolve() == (bundle_dir / "skills").resolve()
        assert not (sandbox_skills / "old-skill").exists()
        assert (sandbox_skills / "alpha-skill").exists()
    finally:
        shutil.rmtree(box2, ignore_errors=True)

