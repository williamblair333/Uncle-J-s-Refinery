#!/usr/bin/env python3
"""Replay bench for every hook that changes agent behaviour.

Reads the hooks from .claude/settings.json (project) and ~/.claude/settings.json (global),
pulls real events out of recent Claude Code transcripts, and pipes each event through each
matching hook exactly as Claude Code would. Reports, per hook:

  fires / events   how often it would block or inject today
  errors           runs that exited with neither 0 nor 2 (a broken hook)
  false / labelled hand labels from bench/hook-labels.jsonl (precision on what is labelled)
  replay-only      fires now where the live session was not blocked with the same message
  live-only        blocked live with one of its messages, but not now

Replayed events: PreToolUse (every tool call), PostToolUse (every successful tool call, with
the transcript's toolUseResult as tool_response; only hooks listed in post_tool_replay run),
UserPromptSubmit (every prompt Bill typed), Stop (each turn's assistant text, passed as
last_assistant_message). A hook whose exit-0 output the harness would drop is counted as
'ignored', not as a fire. --export leaves tool responses out unless --with-responses. Hooks run in a
sandbox: HOME is a temp dir mirroring the real one by symlinks except ~/.claude/state, the hook-blocks log and every
state log point into it, and session ids get a `bench-` prefix so no real pre-mortem
clearance token is read. A hook that writes state must honour one of the env vars set in
make_sandbox(), or the bench writes real state (tests/test_hook_bench.py checks the log).
Hooks listed under live_state in config/hook-bench.json are not run: their answer depends
on git or files as they are now. Nor are leaks_state hooks, which write to a hardcoded real
path the sandbox cannot redirect.

  python3 scripts/hook_bench.py [--days N] [--max-events N] [--hook NAME] [--samples N] [--json]
  python3 scripts/hook_bench.py --export DIR [--days N] [--hook NAME]
  python3 scripts/hook_bench.py --from DIR [--max-events N] [--hook NAME] [--samples N] [--json]
  python3 scripts/hook_bench.py --label KEY true|false [note...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "hook-bench.json"
LABELS = REPO / "bench" / "hook-labels.jsonl"
PROJECTS = Path.home() / ".claude" / "projects"
SETTINGS = [("project", REPO / ".claude" / "settings.json"),
            ("global", Path.home() / ".claude" / "settings.json")]
REPLAYED = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop")
TIMEOUT = 20
RESPONSE_CAP = 20_000   # chars of serialised tool_response kept per PostToolUse event
# Top-level stdout JSON fields Claude Code acts on. JSON output with none of them is dropped
# by the harness: the hook thinks it fired, the model never sees it.
KNOWN_OUTPUT = {"continue", "stopReason", "suppressOutput", "systemMessage", "decision",
                "reason", "hookSpecificOutput"}
LIVE_RE = re.compile(r"^PreToolUse:\S+ hook (?:error|blocking error)[^:]*:\s*(.*)", re.S)
_SKIP_PROMPT = ("<command-", "<local-command", "<task-notification", "Base directory for this skill",
                "[Request interrupted", "Caveat:", "<system-reminder>")


# ── hooks ─────────────────────────────────────────────────────────────────────

def load_config(path: Path = CONFIG) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {"skip": [], "live_state": {}, "names": {}}


def hook_name(command: str, cfg: dict) -> str:
    tag = re.search(r"#\s*([\w.:-]+)\s*$", command)
    if tag:
        return tag.group(1)
    for sub, name in cfg.get("names", {}).items():
        if sub in command:
            return name
    script = re.findall(r"[\w.-]+\.(?:sh|py)\b", command)
    if script:
        return script[-1]
    return "inline-" + hashlib.sha1(command.encode()).hexdigest()[:6]


def load_hooks(cfg: dict, settings=SETTINGS) -> list[dict]:
    """Every hook command in the settings files, with its event, matcher, scope and status."""
    hooks = []
    for scope, path in settings:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        for event, groups in (data.get("hooks") or {}).items():
            for group in groups:
                for h in group.get("hooks", []):
                    cmd = h.get("command") or ""
                    if not cmd:
                        continue
                    status, note = "run", ""
                    if any(s in cmd for s in cfg.get("skip", [])):
                        status, note = "skip", "observability/setup"
                    else:
                        for kind in ("leaks_state", "live_state"):
                            for sub, why in cfg.get(kind, {}).items():
                                if sub in cmd:
                                    status, note = kind, why
                                    break
                            if status != "run":
                                break
                    if status == "run" and event not in REPLAYED:
                        status, note = "not_replayed", f"{event} events are not replayed"
                    elif (status == "run" and event == "PostToolUse"
                          and not any(s in cmd for s in cfg.get("post_tool_replay", []))):
                        # PostToolUse hooks usually act (stage, index, sync); run only the
                        # ones config/hook-bench.json lists as side-effect free.
                        status, note = "not_replayed", "PostToolUse: not in post_tool_replay"
                    hooks.append({"name": hook_name(cmd, cfg), "event": event, "scope": scope,
                                  "matcher": group.get("matcher", ""), "command": cmd,
                                  "status": status, "note": note})
    return hooks


def rewrite_command(command: str, repo: Path = REPO, home: Path | None = None,
                    bundle: Path | None = None) -> str:
    """A `~/.claude/hooks/…` path that symlinks into the repo becomes the repo path; with
    `bundle`, any other existing one is copied (its top-level hooks/ dir) into
    bundle/hooks/ and the command points at the copy. Everything else is unchanged."""
    if not command:
        return ""
    bundle_path = Path(bundle) if bundle is not None else None
    if home is None:
        home = Path.home()
    repo_resolved = repo.resolve()
    home_resolved = home.resolve()

    prefixes = [r"~", r"\$HOME", r"\$\{HOME\}"]
    for h in (home, home_resolved):
        s = str(h).rstrip("/")
        if s and re.escape(s) not in prefixes:
            prefixes.append(re.escape(s))
    prefix_pattern = "|".join(prefixes)
    pattern = re.compile(rf"(?:{prefix_pattern})/\.claude/hooks/([^\s\"'>;&|()#]+)")

    def replace(match: re.Match) -> str:
        subpath = match.group(1)
        for h in (home, home_resolved):
            candidate = h / ".claude" / "hooks" / subpath
            if candidate.is_symlink():
                try:
                    target = candidate.resolve()
                    if target != repo_resolved:
                        target.relative_to(repo_resolved)
                        return str(target)
                except (ValueError, RuntimeError):
                    pass
            if bundle_path is not None and (candidate.exists() or candidate.is_symlink()):
                hooks_dir = h / ".claude" / "hooks"
                top_name = Path(subpath).parts[0]
                src_top = hooks_dir / top_name
                dest_top = bundle_path / "hooks" / top_name
                try:
                    if src_top.is_dir():
                        dest_top.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(src_top, dest_top, dirs_exist_ok=True)
                    elif src_top.is_file():
                        dest_top.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_top, dest_top)
                    else:
                        continue
                    copy_path = (bundle_path / "hooks" / subpath).resolve()
                    return str(copy_path)
                except OSError:
                    pass
        return match.group(0)

    return pattern.sub(replace, command)


def export_dest_ok(dest: Path, repo: Path = REPO) -> bool:
    """A bundle may go outside the repo, or inside it only where git ignores it: its
    events.jsonl is transcript text and the Gitea mirror publishes to GitHub."""
    try:
        Path(dest).resolve().relative_to(repo.resolve())
    except ValueError:
        return True
    probe = Path(dest).resolve() / "events.jsonl"
    r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(probe)],
                       capture_output=True)
    return r.returncode == 0


def load_bundle_settings(from_dir: Path) -> list[tuple[str, Path]]:
    bundle_dir = Path(from_dir)
    files = sorted(bundle_dir.glob("settings-*.json"),
                   key=lambda p: (0 if p.name == "settings-project.json" else (1 if p.name == "settings-global.json" else 2), p.name))
    settings = []
    for p in files:
        scope = p.name[len("settings-"):-len(".json")]
        settings.append((scope, p))
    return settings


def matches(matcher: str, tool: str) -> bool:
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return matcher == tool


def applies(hook: dict, ev: dict) -> bool:
    if ev["event"] != hook["event"]:
        return False
    if hook["event"] in ("PreToolUse", "PostToolUse") and not matches(hook["matcher"], ev["tool"]):
        return False
    return hook["scope"] == "global" or (ev["cwd"] or "").startswith(str(REPO))


# ── events ────────────────────────────────────────────────────────────────────

def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict))
    return c if isinstance(c, str) else ""


def _response(entry: dict, block: dict):
    """tool_response for a PostToolUse replay: the transcript's toolUseResult, else the
    result text. Anything over RESPONSE_CAP serialised chars becomes truncated text."""
    r = entry.get("toolUseResult", _result_text(block))
    s = r if isinstance(r, str) else json.dumps(r)
    return s[:RESPONSE_CAP] if len(s) > RESPONSE_CAP else r


def is_prompt(entry: dict) -> bool:
    """A prompt the user typed, as opposed to a tool result or harness message."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                         for b in content):
        return False
    text = _text(content).lstrip()
    return bool(text) and not text.startswith(_SKIP_PROMPT)


def _epoch(ts: str) -> float | None:
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (ValueError, TypeError):
        return None


def events_from(path: Path, since: float) -> list[dict]:
    """PreToolUse, UserPromptSubmit and Stop events from one transcript, in order."""
    events, by_tool_id = [], {}
    turn: list[str] = []
    state = {"session": None, "cwd": None}

    def close_turn():
        if turn and state["session"]:
            events.append({"event": "Stop", "session": state["session"], "cwd": state["cwd"],
                           "text": "\n".join(turn).strip()})
        turn.clear()

    try:
        fh = path.open(errors="replace")
    except OSError:
        return []
    with fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("isSidechain"):
                continue
            t = _epoch(entry.get("timestamp", ""))
            if t is not None and t < since:
                continue
            state["session"] = entry.get("sessionId") or state["session"]
            state["cwd"] = entry.get("cwd") or state["cwd"]
            msg = entry.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if entry.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        turn.append(b.get("text", ""))
                    elif b.get("type") == "tool_use":
                        ev = {"event": "PreToolUse", "session": state["session"], "cwd": state["cwd"],
                              "tool": b.get("name", ""), "input": b.get("input") or {}, "live": None}
                        by_tool_id[b.get("id")] = ev
                        events.append(ev)
            elif entry.get("type") == "user":
                if is_prompt(entry):
                    close_turn()
                    events.append({"event": "UserPromptSubmit", "session": state["session"],
                                   "cwd": state["cwd"], "text": _text(content)})
                elif isinstance(content, list):
                    for b in content:
                        if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                            continue
                        ev = by_tool_id.get(b.get("tool_use_id"))
                        if b.get("is_error"):
                            m = LIVE_RE.match(_result_text(b))
                            if m and ev is not None:
                                ev["live"] = m.group(1)
                        elif ev is not None:
                            # PostToolUse fires on success only. toolUseResult is the
                            # structured tool_response the hook saw; older entries lack it.
                            events.append({"event": "PostToolUse", "session": state["session"],
                                           "cwd": state["cwd"], "tool": ev["tool"],
                                           "input": ev["input"], "tool_use_id": b.get("tool_use_id"),
                                           "response": _response(entry, b)})
        close_turn()
    return events


def collect_events(days: float, root: Path = PROJECTS) -> list[dict]:
    since = time.time() - days * 86400
    files = [p for p in root.glob("*/*.jsonl") if p.stat().st_mtime >= since]
    out = []
    for p in sorted(files, key=lambda p: p.stat().st_mtime):
        out.extend(events_from(p, since))
    return out


def load_events(path: Path) -> list[dict]:
    events = []
    try:
        fh = Path(path).open(errors="replace")
    except OSError:
        return []
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


def export_bundle(dest: Path, days: float = 7, hook_filter: str | None = None,
                  cfg: dict | None = None, settings: list[tuple[str, Path]] | None = None,
                  projects_root: Path = PROJECTS, repo: Path = REPO,
                  home: Path | None = None, with_responses: bool = False) -> tuple[int, int]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    if cfg is None:
        cfg = load_config()
    if settings is None:
        settings = SETTINGS

    events = collect_events(days, root=projects_root)
    if not with_responses:
        # PostToolUse events carry tool output (file contents, command output). A bundle is
        # handed to agy, i.e. off this machine; leave them out unless asked for.
        events = [e for e in events if e["event"] != "PostToolUse"]
    with (dest / "events.jsonl").open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    total_hooks = 0
    for scope, path in settings:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        new_hooks = {}
        for event, groups in (data.get("hooks") or {}).items():
            new_groups = []
            for group in groups:
                new_h_list = []
                for h in group.get("hooks", []):
                    cmd = h.get("command") or ""
                    if not cmd:
                        continue
                    if hook_filter and hook_filter not in hook_name(cmd, cfg):
                        continue
                    new_cmd = rewrite_command(cmd, repo=repo, home=home, bundle=dest)
                    new_h = dict(h)
                    new_h["command"] = new_cmd
                    new_h_list.append(new_h)
                    total_hooks += 1
                if new_h_list:
                    new_group = dict(group)
                    new_group["hooks"] = new_h_list
                    new_groups.append(new_group)
            if new_groups:
                new_hooks[event] = new_groups
        out_data = dict(data)
        out_data["hooks"] = new_hooks
        (dest / f"settings-{scope}.json").write_text(json.dumps(out_data, indent=2) + "\n", encoding="utf-8")

    skills_home = home if home is not None else Path.home()
    skills_dir = skills_home / ".claude" / "skills"
    if not skills_dir.is_dir():
        skills_dir = skills_home.resolve() / ".claude" / "skills"
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir()):
            try:
                skill_md = entry / "SKILL.md"
                if skill_md.is_file():
                    stub = dest / "skills" / entry.name / "SKILL.md"
                    stub.parent.mkdir(parents=True, exist_ok=True)
                    stub.write_text("", encoding="utf-8")
            except OSError:
                continue

    return len(events), total_hooks


def event_key(hook: str, ev: dict) -> str:
    if ev["event"] == "PreToolUse":
        body = json.dumps(ev.get("input"), sort_keys=True)
    elif ev["event"] == "PostToolUse":
        body = ev.get("tool_use_id") or json.dumps([ev.get("input"), ev.get("response")], sort_keys=True)
    else:
        body = ev.get("text", "")
    return hashlib.sha1(f"{hook}\0{ev['event']}\0{body[:4000]}".encode()).hexdigest()[:12]


def payload(ev: dict) -> dict:
    p = {"session_id": "bench-" + (ev["session"] or "x"), "cwd": ev["cwd"] or str(REPO),
         "hook_event_name": ev["event"], "permission_mode": "default"}
    if ev["event"] == "PreToolUse":
        p.update(tool_name=ev["tool"], tool_input=ev["input"])
    elif ev["event"] == "PostToolUse":
        p.update(tool_name=ev["tool"], tool_input=ev["input"], tool_response=ev.get("response"),
                 tool_use_id=ev.get("tool_use_id") or "")
    elif ev["event"] == "UserPromptSubmit":
        p["prompt"] = ev["text"]
    else:
        p.update(stop_hook_active=False, last_assistant_message=ev["text"])
    return p


# ── running ───────────────────────────────────────────────────────────────────

def make_sandbox(bundle: Path | None = None, home: Path | None = None) -> tuple[Path, dict]:
    box = Path(tempfile.mkdtemp(prefix="hook-bench-"))
    claude = box / ".claude"
    (claude / "state").mkdir(parents=True)
    # Mirror HOME so `~/…` resolves as it did live (a guard judging `cd ~/.claude/projects`
    # must see that it exists), but give ~/.claude/state a fresh dir: that's where hooks
    # write. Every other ~/.claude entry and every other HOME entry is a symlink.
    if home is None:
        home = Path.home()
    for real in (home.iterdir() if home.is_dir() else []):
        if real.name != ".claude":
            (box / real.name).symlink_to(real)
    if (home / ".claude").is_dir():          # absent on a clean machine (CI)
        for real in (home / ".claude").iterdir():
            if real.name != "state":
                (claude / real.name).symlink_to(real)
    if bundle is not None:
        bundle_skills = Path(bundle) / "skills"
        if bundle_skills.is_dir():
            target_skills = claude / "skills"
            if target_skills.is_symlink() or target_skills.exists():
                if target_skills.is_dir() and not target_skills.is_symlink():
                    shutil.rmtree(target_skills)
                else:
                    target_skills.unlink()
            target_skills.symlink_to(bundle_skills.resolve())
    (box / "proj").mkdir()  # exists but empty: hook-blocks.log appends fail harmlessly
    env = {**os.environ, "HOME": str(box), "UNCLE_J_PROJ_ROOT": str(box / "proj"),
           "SURFACE_GUARD_LOG": str(box / "surface.log"),
           "SELF_CHECK_LOG": str(box / "self-check.jsonl"),
           "WORKAROUND_SCAN_LOG": str(box / "workaround.jsonl"),
           "SELF_WORK_DIR": str(claude / "state" / "self-work"),
           "SELF_WORK_LOG": str(box / "self-work.jsonl"),
           "HOOK_BENCH": "1"}
    return box, env


def classify(event: str, rc: int, out: str, err: str) -> tuple[str, str]:
    """('block'|'inject'|'ignored'|'error'|'pass', message) for one hook run.

    'ignored': exit 0 with output Claude Code drops — JSON with no field it reads, or plain
    text on an event whose stdout only reaches the debug log."""
    if rc == 2:
        return "block", err.strip() or out.strip()
    if rc != 0:
        return "error", (err.strip() or out.strip() or f"exit {rc}")[:300]
    out = out.strip()
    if not out:
        return "pass", ""
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if isinstance(data, dict):
        hso = data.get("hookSpecificOutput") or {}
        if hso.get("permissionDecision") in ("deny", "ask"):
            return "block", hso.get("permissionDecisionReason", "")
        if data.get("decision") == "block":
            return "block", data.get("reason", "")
        if hso.get("additionalContext") and event != "PreToolUse":
            return "inject", hso["additionalContext"]
        if not set(data) & KNOWN_OUTPUT:
            return "ignored", out
        return "pass", ""
    if event in ("UserPromptSubmit", "SessionStart"):
        return "inject", out
    return "ignored", out


def run_one(hook: dict, ev: dict, env: dict) -> tuple[str, str]:
    cwd = ev["cwd"] if ev["cwd"] and os.path.isdir(ev["cwd"]) else str(REPO)
    try:
        r = subprocess.run(["bash", "-c", hook["command"]], input=json.dumps(payload(ev)),
                           capture_output=True, text=True, env=env, cwd=cwd, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "error", "timeout"
    return classify(hook["event"], r.returncode, r.stdout, r.stderr)


def _prefix(msg: str) -> str:
    return re.sub(r"\s+", " ", msg or "").strip()[:40]


def bench_hook(hook: dict, events: list[dict], env: dict) -> dict:
    """Run one hook over the events it applies to; events must already be filtered."""
    res = {"events": len(events), "fires": [], "errors": Counter(), "ignored": 0}
    replayed, prefixes = [], set()
    for ev in events:
        verdict, msg = run_one(hook, ev, env)
        replayed.append((ev, verdict, msg))
        if verdict in ("block", "inject"):
            res["fires"].append({"key": event_key(hook["name"], ev), "verdict": verdict,
                                 "message": msg, "event": ev})
            prefixes.add(_prefix(msg))
        elif verdict == "error":
            res["errors"][msg[:120]] += 1
        elif verdict == "ignored":
            res["ignored"] += 1
    replay_only = live_only = 0
    if hook["event"] == "PreToolUse":
        for ev, verdict, msg in replayed:
            fired = verdict in ("block", "inject")
            live = _prefix(ev.get("live")) if ev.get("live") is not None else None
            if fired and live != _prefix(msg):
                replay_only += 1
            elif not fired and live is not None and live in prefixes:
                live_only += 1
    res["replay_only"], res["live_only"] = replay_only, live_only
    return res


# ── labels and report ─────────────────────────────────────────────────────────

def load_labels(path: Path = LABELS) -> dict:
    labels = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return labels
    for line in lines:
        try:
            d = json.loads(line)
            labels[d["key"]] = d
        except (ValueError, KeyError, TypeError):
            continue
    return labels


def add_label(key: str, verdict: str, note: str, path: Path = LABELS) -> None:
    if verdict not in ("true", "false"):
        raise SystemExit("verdict must be true or false")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"key": key, "verdict": verdict, "note": note,
                            "ts": time.strftime("%Y-%m-%d")}) + "\n")


def snippet(ev: dict, n: int = 140) -> str:
    if ev["event"] in ("PreToolUse", "PostToolUse"):
        inp = ev["input"] if isinstance(ev["input"], dict) else {}
        body = inp.get("command") or inp.get("file_path") or inp.get("prompt") or json.dumps(ev["input"])
        s = f"{ev['tool']}: {body}"
    else:
        s = ev.get("text", "")
    return re.sub(r"\s+", " ", str(s))[:n]


def summarise(hook: dict, res: dict, labels: dict) -> dict:
    fires = res["fires"]
    lab = [labels[f["key"]] for f in fires if f["key"] in labels]
    false = sum(1 for d in lab if d.get("verdict") == "false")
    return {"name": hook["name"], "event": hook["event"], "scope": hook["scope"],
            "events": res["events"], "fires": len(fires),
            "rate": round(len(fires) / res["events"], 4) if res["events"] else None,
            "errors": sum(res["errors"].values()), "error_kinds": dict(res["errors"].most_common(3)),
            "ignored": res.get("ignored", 0),
            "labelled": len(lab), "false": false,
            "precision": round(1 - false / len(lab), 3) if lab else None,
            "replay_only": res["replay_only"], "live_only": res["live_only"],
            "unlabelled": [{"key": f["key"], "verdict": f["verdict"], "event": snippet(f["event"]),
                            "message": _prefix(f["message"])}
                           for f in fires if f["key"] not in labels]}


def skill_counts(events: list[dict]) -> Counter:
    return Counter((e["input"] or {}).get("skill", "?") for e in events
                   if e["event"] == "PreToolUse" and e["tool"] == "Skill" and isinstance(e["input"], dict))


def render(rows: list[dict], skipped: list[dict], skills: Counter, prompts: int, days: float,
           samples: int) -> str:
    out = [f"hook bench — last {days:g} days, transcripts in {PROJECTS}", ""]
    out.append(f"{'hook':28} {'event':16} {'events':>7} {'fires':>6} {'rate':>7} {'err':>5} "
               f"{'false/lab':>9} {'repl-only':>9} {'live-only':>9}")
    for r in sorted(rows, key=lambda r: (r["event"], -(r["rate"] or 0))):
        rate = f"{r['rate']:.1%}" if r["rate"] is not None else "—"
        out.append(f"{r['name'][:28]:28} {r['event']:16} {r['events']:>7} {r['fires']:>6} {rate:>7} "
                   f"{r['errors']:>5} {str(r['false']) + '/' + str(r['labelled']):>9} "
                   f"{r['replay_only']:>9} {r['live_only']:>9}")
    for r in rows:
        if r.get("ignored"):
            out.append(f"\n{r['name']} produced output Claude Code drops {r['ignored']}x "
                       "(JSON with no field the harness reads, or stdout on an event that "
                       "only logs it): it thinks it fires, the model never sees it")
        if r["errors"]:
            out.append(f"\n{r['name']} errored {r['errors']}x: " +
                       "; ".join(f"{k!r} ×{v}" for k, v in r["error_kinds"].items()))
    if samples:
        for r in rows:
            if r["unlabelled"]:
                out.append(f"\n{r['name']}: {len(r['unlabelled'])} unlabelled fires "
                           f"(label with: just hook-bench --label KEY true|false note)")
                for u in r["unlabelled"][-samples:]:
                    out.append(f"  {u['key']}  {u['event']}\n                → {u['message']}")
    if skipped:
        out.append("\nnot replayed:")
        for h in skipped:
            out.append(f"  {h['name'][:28]:28} {h['event']:16} {h['status']}: {h['note']}")
    out.append(f"\nskills invoked ({prompts} prompts): " +
               (", ".join(f"{k} {v}" for k, v in skills.most_common()) or "none"))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--max-events", type=int, default=800,
                    help="most recent matching events per hook (0 = all)")
    ap.add_argument("--hook", help="only hooks whose name contains this")
    ap.add_argument("--samples", type=int, default=3, help="unlabelled fires shown per hook")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--label", nargs="+", metavar="ARG", help="KEY true|false [note...]")
    ap.add_argument("--export", metavar="DIR", help="export events and settings to DIR")
    ap.add_argument("--from", dest="from_dir", metavar="DIR", help="read events and settings from DIR")
    ap.add_argument("--with-responses", action="store_true",
                    help="--export: include PostToolUse events, which carry tool output")
    a = ap.parse_args(argv)

    if a.export and a.from_dir:
        ap.error("--export and --from cannot be used together")

    if a.label:
        if len(a.label) < 2:
            ap.error("--label KEY true|false [note...]")
        add_label(a.label[0], a.label[1], " ".join(a.label[2:]))
        print(f"labelled {a.label[0]} {a.label[1]}")
        return 0

    if a.export:
        dest = Path(a.export)
        if not export_dest_ok(dest):
            ap.error(f"--export {dest}: inside the repo but not git-ignored. The bundle holds "
                     "private transcript text; use state/… (ignored) or a path outside the repo")
        n_events, n_hooks = export_bundle(dest, a.days, hook_filter=a.hook,
                                          with_responses=a.with_responses)
        print(f"exported {n_events} events, {n_hooks} hooks to {dest}")
        return 0

    cfg = load_config()
    if a.from_dir:
        from_dir = Path(a.from_dir)
        if not from_dir.is_dir():
            ap.error(f"--from directory does not exist: {from_dir}")
        settings = load_bundle_settings(from_dir)
        hooks = load_hooks(cfg, settings=settings)
        events = load_events(from_dir / "events.jsonl")
    else:
        from_dir = None
        hooks = load_hooks(cfg)
        events = collect_events(a.days)

    if a.hook:
        hooks = [h for h in hooks if a.hook in h["name"]]
    runnable = [h for h in hooks if h["status"] == "run"]
    skipped = [h for h in hooks if h["status"] in ("leaks_state", "live_state", "not_replayed")]
    labels = load_labels()
    box, env = make_sandbox(bundle=from_dir)
    try:
        def go(h):
            mine = [e for e in events if applies(h, e)]
            if a.max_events:
                mine = mine[-a.max_events:]
            return summarise(h, bench_hook(h, mine, env), labels)
        with ThreadPoolExecutor(max_workers=min(8, len(runnable) or 1)) as pool:
            rows = list(pool.map(go, runnable))
    finally:
        shutil.rmtree(box, ignore_errors=True)
    prompts = sum(1 for e in events if e["event"] == "UserPromptSubmit")
    skills = skill_counts(events)
    if a.json:
        print(json.dumps({"days": a.days, "hooks": rows, "not_replayed": skipped,
                          "skills": dict(skills), "prompts": prompts}, indent=1, default=str))
    else:
        print(render(rows, skipped, skills, prompts, a.days, a.samples))
    return 0


if __name__ == "__main__":
    sys.exit(main())
