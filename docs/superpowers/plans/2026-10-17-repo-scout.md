# Repo Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An overnight scout that maps the open-source landscape against what Uncle J covers and sends Bill one verified find per morning by Telegram, with yes/maybe/no buttons, and runs a read-only deep evaluation the night after a yes.

**Architecture:** A small stdlib-only Python package `scripts/scout/` does the mechanical work: GitHub facts through `gh api`, state files, message rendering and the run loop. `claude -p` is called only for judgment and returns JSON that's validated before use. The Telegram gateway stays the only `getUpdates` reader; it records `scout:` button presses to an append-only file that the scout reads on its next run.

**Tech Stack:** Python 3.11+ stdlib, `gh` CLI, `claude -p`, bash for cron and the installer, pytest (`just test`).

**Spec:** `docs/superpowers/specs/2026-10-17-repo-scout-design.md`

## Global Constraints

- Overnight work is read-only. Nothing is cloned under the repo root, nothing is installed, and no venv is touched. Repo content comes through `gh api`, not `git clone`.
- Every star count, licence, date and URL in a message comes from a `gh api` response in that run. Model output never supplies facts; any such fields in the judge JSON are ignored.
- At most **one** scout Telegram message per day across all rungs. Nothing is sent while a message is pending.
- A pending message expires after **48 hours** and is recorded as `maybe`.
- Callback data is prefixed `scout:` and is at most 64 bytes. Finds are identified by GitHub's numeric repo `id`, with `full_name` stored next to it.
- Answer memory lives in `scout/answers.json`, which is tracked in git. `state/` is gitignored, so only transient files go there: `state/scout-pending.json`, `state/scout-queue.json`, `state/scout-callbacks.jsonl` and `state/scout.log`.
- The nightly run refuses to scout until `scout/map.md` front matter has `reviewed: true`.
- Telegram messages use `parse_mode=HTML`. Every external string is HTML-escaped, and a rung 1 message targets 600–900 characters with a hard cap of 1200.
- Cron must not overlap 02:30 (memweave sync) or 03:00 (auto-maintain), and it must finish by 07:00. The default is **04:15**.
- Claude calls use `build_claude_argv(claude_bin, "restricted", SCOUT_SYSTEM, prompt)` from `scripts/lib/tg_security.py` (no MCP, dangerous built-ins denied), with cwd set to a scratch dir outside the repo.
- Use `just` recipes as the entry points. Each recipe is one line; the logic lives in the scripts.

## Review Focus

1. **`gh` fails mid-run** (rate limit, network, auth expired): the run logs it and sends nothing. State files stay valid JSON, and the next run retries. → test in Task 2 and Task 6.
2. **The judge returns junk** (prose, partial JSON, invented stars): the find is dropped, the run logs it, and facts in the message still match `gh`. → test in Task 3.
3. **Hostile or odd repo text** (`<script>`, `&`, 5 KB descriptions, emoji): the message stays valid Telegram HTML and under the cap. → test in Task 4.
4. **Repeat or late taps** (Bill taps twice, taps after the 48-hour expiry, or taps a reason before "no"): the first answer wins. A reason is only attached after a "no". Late taps on an expired find upgrade "maybe" to the tapped answer. → test in Task 5.
5. **Archived, forked or already-known repos** (a rename of a rejected repo, or jcodemunch itself): never queued. → test in Task 6.

---

## File Structure

```
scripts/scout/__init__.py
scripts/scout/gh.py          # gh api wrapper → Facts; search
scripts/scout/store.py       # answers, pending, queue, callbacks, inbox, map front matter
scripts/scout/judge.py       # prompts + claude -p + JSON validation
scripts/scout/message.py     # render rung 1/2 text + keyboards; HTML-safe
scripts/scout/run.py         # CLI: seed | run [--dry-run] | status
scripts/lib/tg_security.py   # + record_scout_callback, scout_reason_keyboard
scripts/telegram-gateway-poll.sh   # + scout: branch
features/repo-scout/install.sh
scout/inbox.md  scout/answers.json  (scout/map.md written by seed)
tests/test_scout_gh.py  test_scout_store.py  test_scout_judge.py
tests/test_scout_message.py  test_scout_run.py  (+ cases in test_tg_security.py)
justfile  healthcheck.sh  README.md  CHANGELOG.md  HANDOFF.md
```

Tests import with `sys.path.insert(0, str(ROOT / "scripts"))`, then `from scout import store`.

---

### Task 1: Inbox and answer files, and the scout package skeleton

**Files:**
- Create: `scout/inbox.md`, `scout/answers.json` (`{"finds": {}}`), `scripts/scout/__init__.py`
- Create: `scripts/scout/store.py`
- Test: `tests/test_scout_store.py`

**Interfaces:**
- Produces:
  - `Paths(root: Path)` dataclass with the fields `answers, pending, queue, callbacks, inbox, map, finds_dir, handoffs_dir, log`, matching the spec layout.
  - `load_answers(p) -> dict`, `save_answers(p, data) -> None` (atomic: write `.tmp` then `os.replace`)
  - `record_answer(data, repo_id: int, full_name: str, rung: int, answer: str, reason: str|None, now: datetime) -> dict`. `answer` is one of `yes|maybe|no`.
  - `is_known(data, repo_id: int) -> bool`
  - `read_inbox(p) -> list[str]` returns `owner/repo` strings from lines of the form `- owner/repo` or `- https://github.com/owner/repo(.git)`. Comments and blank lines are ignored.
  - `map_reviewed(p) -> bool` reads the YAML-ish front matter key `reviewed:`. A missing file means False.
  - `load_json(p, default)`, `save_json(p, obj)`: atomic, and a corrupt file logs and returns `default`.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_inbox_parses_urls_and_slugs(tmp_path):
    p = tmp_path / "inbox.md"
    p.write_text("# Inbox\n- https://github.com/MadsLorentzen/ai-job-search.git\n- foo/bar\n<!-- x -->\n")
    assert store.read_inbox(p) == ["MadsLorentzen/ai-job-search", "foo/bar"]

def test_record_answer_and_is_known(tmp_path):
    d = {"finds": {}}
    store.record_answer(d, 42, "a/b", 1, "no", "too heavy", NOW)
    assert store.is_known(d, 42)
    assert d["finds"]["42"]["answer"] == "no" and d["finds"]["42"]["reason"] == "too heavy"

def test_map_reviewed_false_when_missing_or_unset(tmp_path):
    assert store.map_reviewed(tmp_path / "map.md") is False
    (tmp_path / "map.md").write_text("---\nreviewed: false\n---\n")
    assert store.map_reviewed(tmp_path / "map.md") is False
    (tmp_path / "map.md").write_text("---\nreviewed: true\n---\n")
    assert store.map_reviewed(tmp_path / "map.md") is True

def test_load_json_corrupt_returns_default(tmp_path):
    p = tmp_path / "x.json"; p.write_text("{not json")
    assert store.load_json(p, {"q": []}) == {"q": []}
```

- [ ] **Step 2:** `just test tests/test_scout_store.py`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `store.py` with the signatures above. Write `scout/inbox.md` with a one-line header explaining "repos Bill drops here are evaluated ahead of discovered finds" and the entry `- https://github.com/MadsLorentzen/ai-job-search`.
- [ ] **Step 4:** `just test tests/test_scout_store.py`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(scout): state store, inbox with first entry`.

### Task 2: GitHub facts

**Files:** Create `scripts/scout/gh.py`. Test: `tests/test_scout_gh.py`.

**Interfaces:**
- Produces:
  - `Facts` dataclass with the fields `id:int, full_name:str, html_url:str, description:str, stars:int, license:str|None, pushed_at:str, archived:bool, fork:bool, topics:list[str]`
  - `repo_facts(full_name: str, run=_gh) -> Facts | None`. Calls `gh api repos/{full_name}`. Returns None on a non-zero exit or bad JSON. The returned `full_name` comes from the response, so renames resolve.
  - `search(query: str, limit: int = 10, run=_gh) -> list[Facts]`. Calls `gh api -X GET search/repositories -f q=... -f sort=stars -f per_page=N` and drops archived repos and forks.
  - `readme(full_name: str, run=_gh) -> str`. Uses `gh api repos/{x}/readme -H "Accept: application/vnd.github.raw"` and caps the text at 20 000 chars. Returns `""` on failure.
  - `_gh(args: list[str]) -> tuple[int, str]`. A subprocess wrapper with a 30 s timeout.

- [ ] **Step 1: Write failing tests** using a fake `run` that returns canned JSON:
  - `test_repo_facts_maps_fields`: `stars == 49478`, `license == "MIT"`, `id` is an int.
  - `test_repo_facts_rename_uses_response_name`: requesting `old/name` returns `full_name == "new/name"`.
  - `test_repo_facts_gh_failure_returns_none`: `run` returns `(1, "")`, so the result is None.
  - `test_search_drops_archived_and_forks`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS. Then a live smoke test: `.venv/bin/python -c "import sys;sys.path.insert(0,'scripts');from scout import gh;print(gh.repo_facts('MadsLorentzen/ai-job-search'))"` prints real facts.
- [ ] **Step 5:** Commit: `feat(scout): gh facts and search`.

### Task 3: Judge (Claude, JSON only)

**Files:** Create `scripts/scout/judge.py`. Test: `tests/test_scout_judge.py`.

**Interfaces:**
- Consumes: `Facts` (Task 2).
- Produces:
  - `inventory(root: Path) -> str`. A compact text of what Uncle J has: server names from `mcp-clients/claude-code-mcp.json.tmpl` (`mcpServers` keys), directory names under `global-skills/`, the CLAUDE.md "Tools by modality" table rows, and `scripts/*` basenames.
  - `seed_prompt(inv: str) -> str` asks for 15–20 categories, each with `{name, status: covered|thin|blank, why, queries: [≤3 GitHub search strings]}`.
  - `pick_prompt(inv: str, category: str, candidates: list[Facts], readmes: dict[str,str]) -> str` asks for `{pick: full_name|null, gap, take, risk, fit: bool, scores: {tokens, accuracy, creativity, offline}}`.
  - `eval_prompt(inv: str, facts: Facts, readme: str, skill_text: str) -> str` embeds the text of `global-skills/agent-harness-backend-adoption-eval/SKILL.md` (or the library variant when the find is a library) and asks for `{verdict: adopt|trial|reject, summary, trial_sketch, risks: [..]}`.
  - `ask(prompt: str, claude_bin: str, call=_claude) -> dict | None`. Takes the first `{...}` JSON object from stdout and validates it against the schema of the prompt kind. Returns None on any failure. `_claude` uses `build_claude_argv(..., "restricted", ...)` with cwd set to a `tempfile.mkdtemp()` and a 300 s timeout.
  - `validate_pick(d) -> dict | None`, `validate_seed(d) -> dict | None`, `validate_eval(d) -> dict | None`. Scores are clamped to ints 0–5; unknown keys (including any `stars`, `license` or `url`) are dropped.

- [ ] **Step 1: Failing tests:**
  - `test_validate_pick_drops_fact_fields`: input with `"stars": 999999` comes out with no `stars` key.
  - `test_ask_returns_none_on_prose`: `call` returns `"Sure! here you go"`, so the result is None.
  - `test_ask_extracts_json_after_preamble`.
  - `test_validate_pick_rejects_bad_scores`: a score of `"high"` makes the result None.
  - `test_inventory_lists_jcodemunch_and_memweave`, run against the real repo root.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Each prompt ends with "Respond with ONLY one JSON object", the same convention as `stack-alerts-send.sh`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(scout): judge prompts with validated JSON`.

### Task 4: Message rendering

**Files:** Create `scripts/scout/message.py`. Test: `tests/test_scout_message.py`.

**Interfaces:**
- Consumes: `Facts`, a validated pick or eval dict.
- Produces:
  - `render_find(category: str, status: str, facts: Facts, pick: dict, source: str) -> str`. Follows the layout in spec §8. `source` is `"inbox"` or `"discovered"`; the inbox shows "📥 from your inbox" in place of the category line. The facts line is built only from `facts`.
  - `render_eval(facts: Facts, ev: dict) -> str`.
  - `keyboard_find(repo_id: int) -> str` builds the JSON `[[{"text":"✅ Yes, evaluate","callback_data":"scout:yes:<id>"},{"text":"🤔 Maybe","callback_data":"scout:maybe:<id>"},{"text":"❌ No","callback_data":"scout:no:<id>"}]]`.
  - `keyboard_eval(repo_id: int) -> str` produces the same row with the labels "✅ Hand off for a trial / 🤔 Maybe / ❌ No" and the prefix `scout:e-yes:` / `scout:e-maybe:` / `scout:e-no:`.
  - `MAX_LEN = 1200`. Longer text is cut at a sentence boundary from the take; the facts line and the score line are never cut.

- [ ] **Step 1: Failing tests:**
  - `test_render_escapes_html`: a description of `<script>&` comes out as `&lt;script&gt;&amp;`.
  - `test_render_caps_length_keeps_facts`: a 5 KB take gives `len <= 1200` with `★49478` still present.
  - `test_keyboard_callback_data_under_64_bytes`: holds for `repo_id=2**40`.
  - `test_render_find_inbox_label`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5:** Commit: `feat(scout): telegram message rendering`.

### Task 5: Gateway records scout taps; answers are applied

**Files:**
- Modify: `scripts/lib/tg_security.py` to add two functions.
- Modify: `scripts/telegram-gateway-poll.sh`, adding an `elif cq_data.startswith("scout:")` branch before the `("approve","skip")` branch.
- Modify: `scripts/scout/store.py` to add `apply_callbacks`.
- Test: `tests/test_tg_security.py` (append), `tests/test_scout_store.py` (append).

**Interfaces:**
- Produces:
  - `record_scout_callback(path: str, message_id: int, data: str) -> bool` in tg_security. It validates `data` against `^scout:(yes|maybe|no|e-yes|e-maybe|e-no|r-have|r-goals|r-heavy|r-later):\d{1,20}$` and appends one JSON line `{"message_id","data","ts"}`. Invalid data returns False and writes nothing.
  - `scout_reason_keyboard(repo_id: int) -> str` builds reason buttons for "already have it" `r-have`, "not my goals" `r-goals`, "too heavy" `r-heavy` and "not now" `r-later`.
  - In the gateway: on a valid `scout:no:<id>` or `scout:e-no:<id>`, call `editMessageReplyMarkup` with `scout_reason_keyboard`. On a reason tap, call `editMessageReplyMarkup` with an empty keyboard. For every `scout:` tap, `answer_callback` as before.
  - `apply_callbacks(paths: Paths, answers: dict, pending: dict|None, now) -> tuple[dict, dict|None]` in store. It reads the JSONL, applies taps in order, then truncates the file atomically. Rules: the first `yes/maybe/no` per find wins. A reason attaches only when the recorded answer is `no`. A tap on a find already expired to `maybe` replaces it once. Any answer clears `pending` when the message_id matches. A pending entry older than 48 h becomes `maybe` and clears pending.

- [ ] **Step 1: Failing tests:**
  - `test_record_scout_callback_rejects_bad_data`: data of `scout:rm -rf:1` returns False and the file is absent.
  - `test_record_scout_callback_appends`: two calls give two lines.
  - `test_apply_first_answer_wins`: `yes` then `no` leaves `yes`.
  - `test_apply_reason_only_after_no`: `r-heavy` with no "no" is ignored; after "no" the reason is `"too heavy"`.
  - `test_apply_expiry_48h_to_maybe`: pending `sent_at` is now − 49 h, so the result is `maybe` and pending is None.
  - `test_apply_late_tap_upgrades_expired_maybe`.
  - `test_stack_alert_callbacks_unchanged`: the existing `record_stack_callback` tests still pass (regression).
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS). Do not touch the offset logic, the lock, or `getUpdates` in the gateway.
- [ ] **Step 5:** `bash -n scripts/telegram-gateway-poll.sh`, then commit: `feat(scout): gateway records scout taps; apply answers`.

### Task 6: The run loop: seed, nightly run, dry run, status

**Files:** Create `scripts/scout/run.py`. Modify `justfile`. Test: `tests/test_scout_run.py`.

**Interfaces:**
- Consumes: everything above. Sends with `subprocess.run(["bash","-c",'source lib/notify.sh && notify_send_pitch "$1" "$2"',"_",text,kb])`, which returns the message_id on stdout.
- Produces the CLI `python3 scripts/scout/run.py {seed|run|status} [--dry-run] [--root PATH]`:
  - `seed`: `inventory`, then `seed_prompt` and `ask`. For each category it checks that at least one query returns ≥1 search result (otherwise the query is dropped). It writes `scout/map.md` with front matter `reviewed: false`, a table (category | status | why | queries) and a `last_scouted: {}` block. It refuses to overwrite a map with `reviewed: true` unless `--force` is given.
  - `run`, in this order: (1) `apply_callbacks`; (2) for each find answered `yes` at rung 1 with no eval yet, run the eval (`readme`, `eval_prompt`, `ask`), write `scout/finds/<owner>__<repo>.md`, and enqueue a rung 2 message; for each `e-yes`, write `scout/handoffs/<owner>__<repo>.md`; (3) enqueue inbox entries not yet known, with facts from `repo_facts`; (4) if `map_reviewed`, pick the category (rule below), `search` up to 3 queries × 10, drop `is_known` repos and repos whose name matches the inventory, take the top 5 by stars, fetch readmes, then `pick_prompt` and `ask`; enqueue the pick if `fit` is true; (5) if there's no pending message and the queue isn't empty, send the first item. Priority is rung 2, then inbox, then discovered. Write pending `{message_id, repo_id, rung, sent_at}`. `--dry-run` prints the message and keyboard instead of sending, and writes no pending.
  - **Category rotation:** among categories, pick the one with the oldest `last_scouted` (never scouted counts as oldest). Covered categories are eligible only when `last_scouted` is more than 30 days old. Ties go to blank, then thin, then covered.
  - `status`: prints whether the map is reviewed, the queue length, the pending item and its age, and counts of yes/maybe/no.
  - Any exception inside a step logs to `state/scout.log` and moves on to the next step. Exit code 0 unless state can't be written.
- `justfile`: add `scout-seed`, `scout *args` (→ `run.py run {{args}}`) and `scout-status`, each one line.

- [ ] **Step 1: Failing tests** (fakes for gh, judge and send; `--root tmp_path`):
  - `test_run_skips_discovery_until_map_reviewed`: the inbox item is still queued and sent.
  - `test_run_never_sends_while_pending`.
  - `test_run_priority_rung2_then_inbox_then_discovered`.
  - `test_run_skips_known_and_renamed_repo`: answers holds id 42 as `no`, and search returns id 42 under a new name, so it's not queued.
  - `test_run_gh_failure_sends_nothing_state_valid`: `search` and `repo_facts` fail, so no send happens and the JSON files parse.
  - `test_run_writes_nothing_outside_scout_and_state`: snapshot the tree before and after.
  - `test_rotation_prefers_never_scouted_blank`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Live dry run:** `just scout --dry-run` prints the ai-job-search message with real `gh` facts. Check the stars and licence against `gh api repos/MadsLorentzen/ai-job-search` by hand.
- [ ] **Step 6:** Commit: `feat(scout): run loop, seed, status, just recipes`.

### Task 7: Seed the map (stop for Bill)

- [ ] **Step 1:** `just scout-seed`. Expected: `scout/map.md` exists with 15–20 categories and `reviewed: false`.
- [ ] **Step 2:** Sanity check: code intelligence and memory are `covered`, and voice/wake word is `thin` or `blank`. If not, fix the inventory or the prompt (Task 3) and re-seed.
- [ ] **Step 3:** Commit `scout/map.md`: `feat(scout): seed capability map (unreviewed)`.
- [ ] **Step 4: STOP.** Show Bill the map. Nightly discovery stays off until he sets `reviewed: true`. Inbox items still flow.

### Task 8: Cron installer, healthcheck, docs

**Files:** Create `features/repo-scout/install.sh`. Modify `healthcheck.sh`, `README.md`, `CHANGELOG.md`, `HANDOFF.md`.

**Interfaces:**
- `install.sh`: copies `features/stack-alerts/install.sh`. The cron marker is `uncle-j-repo-scout`. The entry is `15 4 * * * PATH=... CLAUDE_BIN=... python3 $PROJ_ROOT/scripts/scout/run.py run >> $PROJ_ROOT/state/scout.log 2>&1`. Supports `--uninstall`. Uses `lib/feature-helpers.sh` `install_cron` and `remove_cron`.
- Healthcheck: a check named `repo-scout`. It's skipped (not failed) when the cron isn't installed. It warns when the cron is installed but `state/scout.log` has no line from the last 36 h.

- [ ] **Step 1:** Write the installer. Test it with `bash install.sh` then `crontab -l | grep uncle-j-repo-scout` (one line), and `bash install.sh --uninstall` (line gone). Re-install only if Bill says so; **don't leave the cron installed by default.**
- [ ] **Step 2:** Add the healthcheck. Run `just health` and expect `repo-scout` to show as skipped or OK.
- [ ] **Step 3:** Docs: a README feature entry, a CHANGELOG entry and a HANDOFF entry (including "map awaiting review; cron not installed").
- [ ] **Step 4:** `just test` (full suite). Expected: all pass.
- [ ] **Step 5:** Commit: `feat(scout): cron installer, healthcheck, docs`.
