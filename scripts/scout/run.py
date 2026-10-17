"""Repo scout entry point: seed the capability map, run one night, or show status.

    python3 scripts/scout/run.py seed [--force]
    python3 scripts/scout/run.py run [--dry-run]
    python3 scripts/scout/run.py status

Cron runs `run` once a night. Every step logs to state/scout.log and a failing step never
stops the next one. Nothing is cloned or installed: repo content comes through `gh api`.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scout import gh, judge, message, store  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_SKILL = REPO_ROOT / "global-skills" / "agent-harness-backend-adoption-eval" / "SKILL.md"
COVERED_RECHECK = datetime.timedelta(days=30)
STATUS_RANK = {"blank": 0, "thin": 1, "covered": 2}
SOURCE_RANK = {"eval": 0, "inbox": 1, "discovered": 2}
INBOX_CATEGORY = "Bill's inbox"


@dataclass
class Deps:
    facts: Callable
    search: Callable
    readme: Callable
    ask: Callable
    send: Callable
    now: datetime.datetime


def _ts(now: datetime.datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(full_name: str) -> str:
    return full_name.replace("/", "__")


# ── map ──────────────────────────────────────────────────────────────────────

def parse_map(p: Path) -> list:
    cats = []
    try:
        lines = Path(p).read_text(encoding="utf-8").splitlines()
    except OSError:
        return cats
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not line.lstrip().startswith("|"):
            continue
        name, status, why, queries = cells
        if status not in STATUS_RANK:
            continue  # header or separator row
        cats.append({"name": name, "status": status, "why": why,
                     "queries": [q.strip() for q in queries.split(";") if q.strip()]})
    return cats


def _cell(s: str) -> str:
    return str(s).replace("|", "/").replace("\n", " ").strip()


def write_map(p: Path, cats: list, now: datetime.datetime) -> None:
    rows = "\n".join(
        f"| {_cell(c['name'])} | {c['status']} | {_cell(c['why'])} | "
        f"{'; '.join(_cell(q) for q in c['queries'])} |" for c in cats)
    text = (
        "---\nreviewed: false\n"
        f"seeded: {_ts(now)}\n---\n"
        "# Capability map\n\n"
        "What the open-source landscape offers, laid over what Uncle J already covers.\n"
        "Edit freely: change a status, rename a category, fix or add search queries\n"
        "(separated by `; `). Set `reviewed: true` above to switch on nightly discovery.\n\n"
        "| Category | Status | Why | Queries |\n|---|---|---|---|\n" + rows + "\n")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def pick_category(cats: list, rotation: dict, now: datetime.datetime):
    """Oldest-scouted category first; ties go blank, thin, covered. A covered category waits
    30 days between looks, counted from the first night it's seen."""
    eligible = []
    for c in cats:
        if not c["queries"]:
            continue
        last = rotation.get(c["name"])
        if c["status"] == "covered":
            if last is None:
                rotation[c["name"]] = _ts(now)
                continue
            if now - store._parse_ts(last) <= COVERED_RECHECK:
                continue
        eligible.append((last or "", STATUS_RANK[c["status"]], c))
    if not eligible:
        return None
    eligible.sort(key=lambda t: (t[0], t[1]))
    return eligible[0][2]


def already_have(full_name: str, inv: str) -> bool:
    m = re.search(r"^MCP servers: (.*)$", inv, re.M)
    if not m:
        return False
    names = [n.strip().lower() for n in m.group(1).split(",") if len(n.strip()) >= 4]
    repo = full_name.split("/")[-1].lower()
    return any(n in repo for n in names)


# ── find pages ───────────────────────────────────────────────────────────────

def _write_find_page(paths: store.Paths, facts, item: dict, ev=None) -> None:
    j = item.get("judgment") or {}
    lines = [f"# {facts.full_name}", "",
             f"- URL: {facts.html_url}", f"- Stars: {facts.stars} (gh, {item['found_at'][:10]})",
             f"- Licence: {facts.license or 'none'}", f"- Last commit: {facts.pushed_at[:10]}",
             f"- Source: {item['source']}" + (f" · {item['category']} ({item['status']})"
                                              if item.get("category") else ""),
             "", facts.description, ""]
    if j.get("take"):
        s = j["scores"]
        lines += ["## Take", "", j.get("gap", ""), "", j["take"], "", f"Risk: {j.get('risk', '')}",
                  "", "Scores: " + ", ".join(f"{k} {v}/5" for k, v in s.items()), ""]
    if ev:
        lines += ["## Evaluation", "", f"Verdict: **{ev['verdict']}**", "", ev["summary"], "",
                  "### Trial sketch", "", ev["trial_sketch"], ""]
        lines += ["### Risks", ""] + [f"- {r}" for r in ev["risks"]] + [""]
    paths.finds_dir.mkdir(parents=True, exist_ok=True)
    page = paths.finds_dir / f"{_slug(facts.full_name)}.md"
    page.write_text("\n".join(lines), encoding="utf-8")


def _write_handoff(paths: store.Paths, key: str, entry: dict) -> None:
    ev = entry.get("eval") or {}
    name = entry.get("full_name", key)
    text = "\n".join([
        f"# Trial hand-off: {name}", "",
        "Bill said yes twice: to the find and to the evaluation. Next step is a throwaway",
        "spike **in a session with Bill**, in a separate working copy outside this repo,",
        "measured against the current setup on tokens, accuracy and offline use.", "",
        f"- Repo: https://github.com/{name}",
        f"- Find page: scout/finds/{_slug(name)}.md", "",
        "## Trial sketch", "", ev.get("trial_sketch", "(see the find page)"), "",
        "## Risks", ""] + [f"- {r}" for r in ev.get("risks", [])] + [""])
    paths.handoffs_dir.mkdir(parents=True, exist_ok=True)
    (paths.handoffs_dir / f"{_slug(name)}.md").write_text(text, encoding="utf-8")


# ── steps ────────────────────────────────────────────────────────────────────

def _queued_ids(queue: list, pending) -> set:
    ids = {q["repo_id"] for q in queue}
    if pending:
        ids.add(pending["repo_id"])
    return ids


def step_evaluate(paths, deps, inv, answers, queue):
    skill = EVAL_SKILL.read_text(encoding="utf-8") if EVAL_SKILL.exists() else ""
    for key, e in answers["finds"].items():
        if e.get("rung") != 1 or e.get("answer") != "yes" or e.get("evaluated"):
            continue
        facts = deps.facts(e.get("full_name", ""))
        if facts is None:
            store.log(paths, f"evaluate: gh facts unavailable for {e.get('full_name')}")
            continue
        ev = deps.ask(judge.eval_prompt(inv, facts, deps.readme(facts.full_name), skill),
                      judge.validate_eval)
        if ev is None:
            store.log(paths, f"evaluate: no valid judgment for {facts.full_name}")
            continue
        e.update({"evaluated": True, "eval": ev})
        item = {"repo_id": facts.id, "full_name": facts.full_name, "rung": 2,
                "source": "eval", "judgment": ev, "found_at": _ts(deps.now)}
        queue.append(item)
        _write_find_page(paths, facts, item, ev)
        store.log(paths, f"evaluate: {facts.full_name} → {ev['verdict']}")


def step_handoffs(paths, deps, inv, answers, queue):
    for key, e in answers["finds"].items():
        if e.get("rung") == 2 and e.get("answer") == "yes" and not e.get("handed_off"):
            _write_handoff(paths, key, e)
            e["handed_off"] = True
            store.log(paths, f"handoff written for {e.get('full_name')}")


def step_inbox(paths, deps, inv, answers, queue, pending):
    for name in store.read_inbox(paths.inbox):
        facts = deps.facts(name)
        if facts is None:
            store.log(paths, f"inbox: gh facts unavailable for {name}")
            continue
        if store.is_known(answers, facts.id) or facts.id in _queued_ids(queue, pending):
            continue
        j = deps.ask(judge.pick_prompt(inv, INBOX_CATEGORY, [facts],
                                       {facts.full_name: deps.readme(facts.full_name)}),
                     judge.validate_pick)
        if j is None:
            store.log(paths, f"inbox: no valid judgment for {name}; retry next run")
            continue
        item = {"repo_id": facts.id, "full_name": facts.full_name, "rung": 1,
                "source": "inbox", "judgment": j, "found_at": _ts(deps.now)}
        queue.append(item)
        _write_find_page(paths, facts, item)
        store.log(paths, f"inbox: queued {facts.full_name}")


def step_discover(paths, deps, inv, answers, queue, pending):
    if not store.map_reviewed(paths.map):
        store.log(paths, "discover: map not reviewed yet; skipping")
        return
    rotation = store.load_json(paths.rotation, {})
    cat = pick_category(parse_map(paths.map), rotation, deps.now)
    store.save_json(paths.rotation, rotation)
    if cat is None:
        store.log(paths, "discover: no category due")
        return
    seen, results = set(), []
    for q in cat["queries"][:3]:
        for f in deps.search(q) or []:
            if f.id not in seen:
                seen.add(f.id)
                results.append(f)
    if not results:
        store.log(paths, f"discover: no search results for '{cat['name']}' (gh down?)")
        return
    rotation[cat["name"]] = _ts(deps.now)
    store.save_json(paths.rotation, rotation)
    taken = _queued_ids(queue, pending)
    cands = [f for f in results if not store.is_known(answers, f.id) and f.id not in taken
             and not already_have(f.full_name, inv)]
    cands = sorted(cands, key=lambda f: -f.stars)[:5]
    if not cands:
        store.log(paths, f"discover: '{cat['name']}' had nothing new")
        return
    readmes = {f.full_name: deps.readme(f.full_name) for f in cands}
    j = deps.ask(judge.pick_prompt(inv, cat["name"], cands, readmes), judge.validate_pick)
    if not j or not j["pick"] or not j["fit"]:
        store.log(paths, f"discover: '{cat['name']}' no pick")
        return
    chosen = next((f for f in cands if f.full_name.lower() == j["pick"].lower()), None)
    if chosen is None:
        store.log(paths, f"discover: pick {j['pick']!r} wasn't a candidate; dropped")
        return
    item = {"repo_id": chosen.id, "full_name": chosen.full_name, "rung": 1,
            "source": "discovered", "category": cat["name"], "status": cat["status"],
            "judgment": j, "found_at": _ts(deps.now)}
    queue.append(item)
    _write_find_page(paths, chosen, item)
    store.log(paths, f"discover: '{cat['name']}' queued {chosen.full_name}")


def step_send(paths, deps, queue, pending, dry_run, out):
    if pending:
        store.log(paths, f"send: message for {pending.get('full_name')} still pending")
        return pending
    if not queue:
        return None
    queue.sort(key=lambda q: SOURCE_RANK[q["source"]])
    item = queue[0]
    facts = deps.facts(item["full_name"])
    if facts is None:
        store.log(paths, f"send: gh facts unavailable for {item['full_name']}; kept queued")
        return None
    if item["rung"] == 2:
        text, kb = message.render_eval(facts, item["judgment"]), message.keyboard_eval(facts.id)
    else:
        text = message.render_find(item.get("category", ""), item.get("status", ""), facts,
                                   item["judgment"], item["source"])
        kb = message.keyboard_find(facts.id)
    if dry_run:
        out(text)
        out(kb)
        return None
    msg_id = deps.send(text, kb)
    if not msg_id:
        store.log(paths, f"send: Telegram send failed for {facts.full_name}; kept queued")
        return None
    queue.pop(0)
    store.log(paths, f"send: sent {facts.full_name} rung {item['rung']} (message {msg_id})")
    return {"message_id": int(msg_id), "repo_id": facts.id, "full_name": facts.full_name,
            "rung": item["rung"], "sent_at": _ts(deps.now)}


def run_once(paths: store.Paths, deps: Deps, inv: str, dry_run=False, out=print) -> None:
    answers = store.load_answers(paths.answers)
    pending = store.load_json(paths.pending, None)
    queue = store.load_json(paths.queue, [])
    try:
        answers, pending = store.apply_callbacks(paths, answers, pending, deps.now)
    except Exception as e:  # noqa: BLE001 — a bad tap file must not stop the night
        store.log(paths, f"apply_callbacks failed: {type(e).__name__}: {e}")

    def save():
        store.save_answers(paths.answers, answers)
        store.save_json(paths.queue, queue)
        if pending is None:
            if paths.pending.exists() and not dry_run:
                paths.pending.unlink()
        elif not dry_run:
            store.save_json(paths.pending, pending)

    save()
    for name, fn in (("evaluate", lambda: step_evaluate(paths, deps, inv, answers, queue)),
                     ("handoffs", lambda: step_handoffs(paths, deps, inv, answers, queue)),
                     ("inbox", lambda: step_inbox(paths, deps, inv, answers, queue, pending)),
                     ("discover", lambda: step_discover(paths, deps, inv, answers, queue,
                                                        pending))):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            store.log(paths, f"{name} failed: {type(e).__name__}: {e}")
        save()
    try:
        pending = step_send(paths, deps, queue, pending, dry_run, out)
    except Exception as e:  # noqa: BLE001
        store.log(paths, f"send failed: {type(e).__name__}: {e}")
    save()


def seed(paths: store.Paths, deps: Deps, inv: str, force=False) -> bool:
    if store.map_reviewed(paths.map) and not force:
        store.log(paths, "seed: map already reviewed; pass --force to replace it")
        return False
    j = deps.ask(judge.seed_prompt(inv), judge.validate_seed)
    if j is None:
        store.log(paths, "seed: no valid judgment")
        return False
    for c in j["categories"]:
        # Drop a query only when it really finds nothing; a failed search (None) keeps it.
        c["queries"] = [q for q in c["queries"] if deps.search(q) != []]
    write_map(paths.map, j["categories"], deps.now)
    store.log(paths, f"seed: wrote {len(j['categories'])} categories")
    return True


def status(paths: store.Paths, now: datetime.datetime, out=print) -> None:
    answers = store.load_answers(paths.answers)
    pending = store.load_json(paths.pending, None)
    queue = store.load_json(paths.queue, [])
    counts = {}
    for e in answers["finds"].values():
        counts[e.get("answer")] = counts.get(e.get("answer"), 0) + 1
    out(f"map reviewed: {store.map_reviewed(paths.map)}")
    out(f"queue: {len(queue)} ({', '.join(q['full_name'] for q in queue) or 'empty'})")
    if pending:
        age = now - store._parse_ts(pending["sent_at"])
        out(f"pending: {pending['full_name']} (rung {pending['rung']}, "
            f"{int(age.total_seconds() // 3600)} h old)")
    else:
        out("pending: none")
    out("answers: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) if counts
        else "answers: none yet")


# ── real dependencies ────────────────────────────────────────────────────────

def _telegram_send(root: Path):
    def send(text: str, keyboard: str):
        script = ('set -a; [ -f .env ] && . ./.env; set +a; '
                  'source lib/notify.sh && notify_send_pitch "$1" "$2"')
        r = subprocess.run(["bash", "-c", script, "_", text, keyboard], cwd=root,
                           capture_output=True, text=True, timeout=60)
        out = r.stdout.strip().splitlines()
        return int(out[-1]) if r.returncode == 0 and out and out[-1].isdigit() else None
    return send


def real_deps(root: Path) -> Deps:
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    return Deps(facts=gh.repo_facts, search=gh.search_checked, readme=gh.readme,
                ask=lambda prompt, validate: judge.ask(prompt, claude_bin, validate),
                send=_telegram_send(root),
                now=datetime.datetime.now(datetime.timezone.utc))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("seed", "run", "status"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--root", default=str(REPO_ROOT))
    a = ap.parse_args(argv)
    paths = store.Paths(Path(a.root))
    if a.cmd == "status":
        status(paths, datetime.datetime.now(datetime.timezone.utc))
        return 0
    deps = real_deps(paths.root)
    inv = judge.inventory(REPO_ROOT)
    store.log(paths, f"{a.cmd} start{' (dry run)' if a.dry_run else ''}")
    if a.cmd == "seed":
        ok = seed(paths, deps, inv, force=a.force)
        print(f"map written to {paths.map}" if ok else "seed did not write a map; see "
              f"{paths.log}")
        return 0 if ok else 1
    run_once(paths, deps, inv, dry_run=a.dry_run)
    store.log(paths, "run done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
