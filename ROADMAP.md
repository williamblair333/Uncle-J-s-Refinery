# ROADMAP — Uncle J's Refinery

Living roadmap. Updated at each session end when items complete or new ones surface.
Completed items age out after ~4 weeks.

---

## In Progress

- **Live Partikus build demo, with Bill watching** (opened 2026-10-17). live_preview and the
  `partikus` MCP server shipped, but Bill hasn't seen a part being built: the only session
  was a batch published after the fact. Open `partikus_watch` first, give the URL alone,
  then build step by step. Not done until Bill has watched one grow. HANDOFF has the steps.

## Planned

- **Thinking chain** (agreed 2026-10-31: goal → problem choice → floor → ideas → proof → learning). Done:
  self-check hook (#249), `think-wider` skill with a build step (#251, #252), Refinery `STANDARDS.md` (#251, #253).
  Open: `meta-question-rate` (the outcome metric, ranked #2 in STANDARDS.md); testing the 5 untested ideas in
  STANDARDS.md (forget-at-will first: planted-fact probe); problem choice (step 2), a separate conversation
  tied to the life goals.
- **[DONE 2026-10-30] Workarounds must surface the cause** — built as below (CHANGELOG 2026-10-30); open: RED/GREEN
  test of the skill trigger (3), and tuning the Stop hook from `~/.claude/state/workaround-scan.jsonl` hit counts. Claude routes around blocks to
  finish today's task and doesn't fix why it was blocked; Bill caught it twice on 10-30 (live campaign as test bed,
  hand-feeding agy game data). Skills fire on the same judgment that fails, so add mechanical detectors that turn
  workaround signals into a required "fix the cause or file it" step:
  1. **delegate wrapper:** `tool_errors` with `auto-denied` → result carries `fix_cause` (the denied tool + path,
     the allow rule to add in `features/antigravity/permissions.json`, ask Bill if outside /opt/proj or secret-like);
     log to `state/agy-denials.jsonl`; `just offload` lists repeat denials. The signal already exists
     (`"warning": "… agy worked around them"`) and nothing acts on it.
  2. **Stop hook:** scan the turn for workaround phrases ("worked around", "hand-fed", "waiting on", "pending live",
     "can't … so") → end-of-turn reminder naming the cause to fix. False positives are cheap.
  3. **Skill trigger** (mtw2's suggestion): "you just worked around something → fix why, or send it to its owner,
     before continuing", in `slowest-loop-first` or a sibling, RED/GREEN tested.
  4. **Status sweeps** flag any "waiting on X" item with no plan to force X.

- **Usage % readable by Claude** (opened 2026-10-30). `/usage` is a built-in dialog Claude can't run or read.
  The status line JSON carries `rate_limits.five_hour|seven_day.used_percentage` + `resets_at` (Pro/Max, after the
  first reply). Plan: a repo status-line script that prints them and saves the block to `~/.cache/claude/usage.json`,
  wired into `statusLine` by `refinery-doctor.sh --fix` (merge with any existing status line, don't replace it).
  Claude then reads the file on "what's my usage?". Numbers are only as fresh as the last reply in some session.

- **Offload follow-ups** (opened 2026-10-26). Re-run `just offload` after a few days of jobs: the
  first real post-fix number (baseline: agy 22/65 ok; CLI jobs counted only from 2026-10-29, #236).
  Per-project columns in `just offload`. Give agy `mkdir/cp/mv/touch` once sandbox-run stops
  binding `~/.cache/uv` writable. Done: qwen 8/8 was test pollution (#229), self-work rotation,
  timeout label (#235), CLI logging (#236), `git grep` rule (#237).

- **Per-repo deny in the servers agy calls** (opened 2026-10-25). agy keeps full use of the stack
  (Bill's call), so it can still reach anatomy-lab through jcodemunch, and its transcripts through
  memweave. Closing that needs a repo filter inside those servers when agy is the caller. The
  delegate guard only sees the prompt.
- **OpenAI backend for delegate** (opened 2026-10-25, when needed). Set `OPENAI_API_KEY` and
  `DELEGATE_OPENAI_MODEL` in the server's env; the code is already in.
- **[DONE 2026-10-23] Ship `dcup` with Uncle J and enforce it.** It's vendored in
  `features/dcup/`, installed by `install.sh` §6b2 and checked by the `refinery-doctor`
  `dcup-guard` check. `dcup_guard.py` blocks `docker compose up` and fixed `docker run -p` that
  bypass dcup (178-case test matrix). The old hook was never wired. Stale claims went from
  82 to 41. Left: run `features/dcup/install.sh` from the main checkout on each host, then
  restart Claude Code. Not covered: commands run inside scripts, and `docker service`/`stack`.

- **Local model lineup: fewest models for every goal** (decided 2026-10-22; text side under
  way). Heretic for text and images, Wan 2.2 for video (and stills if they pass), an image
  model, Whisper, Chatterbox for cloned voices; Ollama and the 9B retired. Steps 1–5 are done
  (faster prefill, host config file, `ask-local-up`, Sinkpoint answered, partikus moved).
  Ollama **can't retire yet**: Klarheit's hourly trials pin `qwen3.5:9b` (step 6). Decided
  2026-10-23: Ollama and the 9B stay, for Klarheit only, until those pre-registered trials end
  (moving a pinned model mid-trial would void them); granite4.2:8b removed; Heretic stays
  127.0.0.1-only (Bill: local only for now). Also left: a small
  llama-server model for the Pi / tc-vmh-03. Speech is done
  (2026-10-23, both CPU only): whisper.cpp large-v3-turbo (`just whisper up -d`, :8092, a 30 s
  clip in ~31-42 s) and Chatterbox Nano cloned voices (`just tts up -d`, :8093, ~5 s a
  sentence); numbers in `docs/STACK.md` "Speech". **Image and video done 2026-10-23:**
  ComfyUI (`just comfy up -d`, `just image`, `just video`, :8188) with Z-Image-Turbo (32 s per
  warm 1024² image) and Wan 2.2 A14B Q4_K_M (8.1 min per 5 s 480p clip); numbers in
  `docs/STACK.md` "Image and video generation". Still to try: Wan stills vs Z-Image (the
  culling test). Plan:
  `docs/proposals/2026-10-22-local-model-lineup.md`.

- **n8n ideas, parked for review** (Bill 2026-10-23: not now) (opened 2026-10-21). n8n would run beside Uncle J for
  webhooks and OAuth SaaS flows. The full list is ranked by project, with traps and four
  decisions for Bill: `docs/proposals/2026-10-21-n8n-ideas.md`. The top picks are bizengine,
  multi-host sync and patentengine deadlines. Resume: "set up n8n".

- **Multiplayer-AI viewer** (Bill 2026-10-23: still needs a game and engine named) (opened 2026-10-17). For watching AI players cooperate or compete
  in a game, in real time. The plan:
  - a game-side bridge (localhost state/action API, fixed screen types; the pattern is from
    CLI-Anything's Slay the Spire II mod);
  - `live_preview` for the board, with the agent's name in each label;
  - Langfuse traces for what each agent saw, said and did.
  - A per-agent lane view needs work in the vendored viewer.
  - Blocked on Bill naming the game and engine.
- **[DONE 2026-10-23] Justfiles** — write_well (status, recall; markdown only; write_well #5,
  `af90396`) and deal-finder (setup, run, status, recall; deal-finder #1 into `master`, its real
  trunk, `24fc4ef`). Both were made in a scratch worktree off the remote trunk, so their dirty
  checkouts were untouched. Earlier history: 2026-10-22 late: aquarius, immortality, larder, patentengine, reciepts,
  tao-intel and jaredrhod done (status, recall); free-energy's slow `just test` fixed (`slow`
  marker, ~2 min; `just test-all` for everything; free-energy #32). Left: write_well and
  deal-finder (big uncommitted trees). Original: (rollout done 2026-10-22 for 18 repos). Left: aquarius
  (markdown only), immortality (docs only), write_well and deal-finder (big uncommitted trees),
  plus the five remote-less repos. Recipe names stay shared: setup, test, run, start, stop,
  status, doctor. The five formerly remote-less repos can get theirs now. free-energy's `just test` didn't finish within 10 minutes (it probably collects
  `accel/tests`); worth a look.
- **Dictation follow-ups** (Bill 2026-10-23: discuss later) (`/opt/proj/voice-line`, opened 2026-10-16). In order: find what
  turns the cursor into a crosshair on Right Alt; decide on `small.en` or `large-v3-turbo`
  (`base.en` mishears jargon); then a KDE autostart entry. GPU whisper is deferred by Bill
  (path in HANDOFF).
- **Review `state/referee.jsonl`** after a few weeks of use (opened 2026-10-15). How often
  does a referee `fail` find a real defect, and how often does it error? Lines with `"retried": true` count soft denies the retry recovered (or not). If it rarely
  catches anything, drop the skill's trigger to on-request only.
- **Re-run the agy permission probes after agy self-updates** (opened 2026-10-15). Table in
  `features/antigravity/README.md`; verified on 1.3.5 only.
- **Compaction restore: report the per-session gap upstream?** (opened 2026-10-12). The
  restore half is now wired (see CHANGELOG 2026-10-12, `refinery-doctor` check
  `jcodemunch-sessionstart`). jcodemunch's live journal is one file per host, not keyed by
  `session_id`. So with two sessions open, a compaction in one can restore the other's focus
  files. That's low harm, because the block only lists files and searches. Decide whether to
  file it with jgravelle/jcodemunch-mcp. A custom snapshot hook (tasks, decisions, prompts) is
  **not** planned: Claude Code's compaction summary already carries those.
- **REA upstream follow-up** (opened 2026-10-12). **#2188 was MERGED 2026-10-14** (merge
  `41a2e84`; the maintainer addressed the review threads himself). #2187 (design issue, `--scope
  local`) is still open, labelled `enhancement`/`P2: medium`/`area: setup`. As of 2026-10-23 it has
  no maintainer reply, only two third-party comments: a design review and a native-Windows quoting
  workaround. If they say "PR welcome", the touched modules are listed in #2187. Install Node
  ≥22.19 first, since REA's checks need it.
- **REA in Docker, two containers** (planned 2026-10-22, **waiting for Bill's "build it"**).
  `docker/rea/` with an Investigator image (REA 6.7.0, Ghidra 12.1.4, Node 24, JDK 21) and a
  Builder image with no Docker socket, pinned in `versions.env`, `just rea-update` /
  `rea-rollback`. Plan: `review/2026-10-22-rea-in-docker.md` (main host).
- **Large-model splitter for the A1 mini ("bigprint")** (spec 2026-10-22, **waiting for Bill**).
  A full clean-room spec (deterministic grid splits only, to design around US10025882B2) sits in
  `review/luban-rebuild-handoff.md` (main host). Needs Bill's go, where the new repo lives, and
  his three open items: filament for gram estimates, connector default, laser outputs.
- **[DONE 2026-10-22] grep-guard false positive on an unexpanded glob** — globs now expand
  against the session cwd and each match is judged; `-r` on a plain non-source file is
  allowed; `cat scripts/*` (which hid source) is now denied. Baseline in audit-baselines.md.
  Original: (found 2026-10-22). `grep -rn X docs/*.md
  README.md SECURITY.md` was blocked: the hook sees the literal `docs/*.md`, which isn't a real
  path, so it can't tell the targets are markdown. Expand globs, or judge a glob by its
  extension, before deciding. Needs its own adversarial pass (a `*.py` glob must stay denied).
- **Track upstream issue [dwarvesf/claude-guardrails#20](https://github.com/dwarvesf/claude-guardrails/issues/20)**
  (filed 2026-10-22): the escalation hook's grep reads its `--…` pattern as an option. If they
  say "PR welcome", send the `-e` fix. Until it lands, `scripts/fix-guardrails-grep.sh` (run by
  `install-guardrails.sh`) keeps the local copy repaired. Status 2026-10-23: #17 and #20 are both
  open with zero comments. The repo's last push was 2026-09-08 (#18/#19), so the maintainer is
  quiet rather than declining.
- **Push access from tc-vmh-03** (opened 2026-10-05). `~/.ssh/github` is rejected by GitHub,
  there's no `gh`, and no Gitea remote, so this host can commit but not push.

- **Jarvis track** (Bill 2026-10-23: later) (opened 2026-10-04). Bill wants Uncle J to grow into a general assistant
  that handles whatever he asks. **Two homes, one Jarvis:** this repo is the engine (MCP
  servers, crons, every commit), and `/opt/proj/jaredrhod` is where Bill talks to it (the
  Jarvis persona in its `CLAUDE.md`, plus the `vaults/brain` vault as long-term memory).
  Build pieces here; don't fork a second persona here or engine code there. Pieces in
  suggested order:
  1. **Daily email triage.** The Gmail and Calendar connectors already exist. Draft replies and
     flag what matters, but only draft: Bill sends. This is the first job that acts for him on
     a schedule rather than when asked.
  2. **Image generation.** Local generation runs (ComfyUI + Z-Image-Turbo, `just image`,
     2026-10-23). Left: wrap it in a small MCP.
  3. **Better voice** for `/opt/proj/voice-line`: the ElevenLabs API or a local voice-cloning
     model.
  4. **Outbound phone calls.** A phone number (Twilio or ElevenLabs agents) plus a voice
     pipeline. This is the largest piece.
  5. **Video generation.** Running: Wan 2.2 14B GGUF Q4_K_M with the lightx2v 4-step LoRAs
     takes 8.1 min per 5 s 832×480 clip on the 3060 (`just video`, measured 2026-10-23). Use it
     for background jobs; use a paid API for anything interactive.

- **Stop being the glue: one front door to every project** (Bill 2026-10-23: later) (opened 2026-10-19). Today Bill `cd`s
  into a project, starts Claude Code, and syncs the Pi and tc-vmh-03 by hand. The goal is to
  minimize his attention per finished outcome (local-first, portable off Claude). Agreed order:
  1. **Measure startup, then trim.** Every session start runs the startup checks and launches
     about 10 MCP servers. Find what's slow before building anything. Meanwhile, keep warm
     sessions (a tmux window per active project, `claude -c`).
  2. **One recipe server plus `ask_project`.** A single MCP server finds every
     `/opt/proj/*/justfile` and exposes its recipes as tools (using a project). `ask_project`
     runs a headless `claude -p` inside a repo and returns a summary (changing a project).
     Recipes with side effects need a confirmation step. This replaces "one MCP server per
     project". A dedicated server (like Partikus) is worth it only for a project called many
     times a day with typed parameters.
  3. **Move recurring "do x" asks to scheduled jobs**, each one reporting its exit code (see
     RELIABILITY.md, "A cron job that never succeeds…").
  4. **One always-on host as the brain**, reached by Telegram or voice. The other hosts become
     clients, which removes the manual sync instead of automating it. Decide which host, and
     what remote access it needs.

- **[DONE 2026-10-22] trafilatura web-to-markdown crawler** — `just web2md` (scripts/web2md.py,
  a uv inline-deps script, so the stack venv is untouched). The open question is answered,
  partly no: it keeps prose well, but on docs.astral.sh it lost 2 of 8 commands (tabbed code),
  emits code unfenced, and turns headings into anchor links (repaired in post-processing;
  trafilatura's XML keeps the levels but drops code blocks entirely). Use it for prose, context7
  for library API docs. The token comparison with WebFetch wasn't run: WebFetch returns a model
  summary, not page text, so the two aren't comparable. Original entry follows.
  **Build a trafilatura web-to-markdown crawler** (opened 2026-10-19, from the scout review).
  It replaces firecrawl, which was rejected: 7 services, 3.4 GiB, and a Playwright browser
  path. trafilatura (Apache-2.0, no Playwright) gave about half the markdown on the same pages
  in 1–2 s. Shape: a script that takes a URL, sitemap or crawl and writes markdown files to a
  folder, then `jdocmunch index_local`, so repeat web lookups become local retrieval. Check that
  the smaller output doesn't drop content that matters, and measure tokens against WebFetch
  on a real task. Verdict and numbers: `review/2026-10-19-firecrawl.md` (main host).
  Resume: "build the trafilatura crawler".
- **[DONE 2026-10-23] firefox-devtools-mcp adopted, per session: `just browser`.** Egress
  measured without root (user+net namespace whose only route is a capturing dummy interface,
  plus a logging SOCKS5 proxy): with `config/firefox-mcp/user.js` and `scripts/firefox-mcp.sh`
  the only contacts are the target sites, for TCP, UDP/QUIC and DNS alike, over 4-minute idles.
  It took three non-pref fixes: `MOZ_REMOTE_SETTINGS_DEVTOOLS=1` (release Firefox ignores the
  remote-settings server pref otherwise), a private `XDG_CONFIG_HOME` (the host's Crash Reports
  store holds a pending telemetry ping any Firefox retries), and node on a local install instead
  of `npx` (which asks the npm registry on every start). Not registered globally. Re-measure
  after a Firefox major upgrade; method in `reviewed/2026-10-19-browser-automation-no-microsoft.md`
  (main host). Original entry follows.
  **Trial firefox-devtools-mcp for browser control** — trial run 2026-10-22, **not adopted yet**.
  It's `@mozilla/firefox-devtools-mcp` now (the old name is deprecated); 0.10.4 works headless
  with system Firefox 150, 34 tools, snapshots 0.4–4.8K chars. But Firefox itself contacts
  Mozilla (detectportal, remote settings, content-signature) besides the target. 19 quieting
  prefs cut that from 7 destinations to 3, not 0. The connect()-only capture also missed
  HTTP/3 (UDP). Next: tcpdump/nft capture, HTTP/3 off, the remaining remote-settings and
  blocklist prefs as a user.js profile; then per-session registration. Notes: the "Trial run"
  section in `review/2026-10-19-browser-automation-no-microsoft.md` (main host).
  Original: (opened 2026-10-19). It's Mozilla's, with
  no Google or Microsoft code at runtime. Snapshots measured 10–40× smaller than
  chrome-devtools-mcp's (~4–23K vs ~186K chars per page); Bill avoids Microsoft, so
  playwright-mcp is out. Plan: register it for sessions that need it only, set
  `SE_AVOID_STATS=true` (Selenium Manager sends stats to plausible.io; the env name is
  inferred, so verify it), install geckodriver locally so it can run offline, and confirm with
  a network capture that only the target site is contacted. Known gaps: no wait tool, and
  network inspection only in the developer preset. Notes:
  `review/2026-10-19-browser-automation-no-microsoft.md`. Resume: "trial the firefox browser".

- **Review `state/ask_local.jsonl`** after about 2 weeks of use (opened 2026-10-04). Does
  offloading save Claude tokens without wrong results acted on? If not, the standing test
  says remove it. Checked 2026-10-22: no data. The log didn't exist until that day's test
  calls, so sessions weren't routing anything through ask_local. Re-check once they do.

- **Codex MCP — GPT through the ChatGPT subscription** (Bill 2026-10-23: later) (opened 2026-10-04). Second of the three
  Hermes-replacement pieces (`ask_local` and the memweave MCP shipped). Codex CLI has an
  MCP-server mode (`codex mcp-server`; confirm the flag at install). Register it so Claude Code
  can get a second opinion or a parallel attempt through OpenAI's own sanctioned client. Needs a
  ChatGPT Plus/Pro login (`codex login`). Gemini can't take this route: Google closed consumer
  OAuth on 2026-06-18, so only an API key works.

- **[DONE 2026-10-23] `occams-razor` description widened** — it now also fires when explaining
  why something is named, built or chosen the way it is. A missed invocation (the BOTvunnix
  case) cost more than an extra skill load on ordinary questions.

- **[CLOSED 2026-10-23] `CampaignGenerator` and `campaign-forge` abandoned** (Bill). No further
  product-gate work; `reviewed/CampaignGenerator` carries a `.no-product-gate` marker.
- **11 non-product repos carry only a local opt-out marker** (Bill 2026-10-23: look later) (opened 2026-09-20). The
  `.no-product-gate` files are untracked in their own repos, so a fresh clone would surface them
  in the audit again. Commit them where the repo is one Bill controls; the four `jaredrhod` forks
  deliberately stay uncommitted to avoid diverging from upstream.
- **[DONE 2026-10-23] `jscrub` automation** — (b) `check-vendor` was already in CI via
  `audit-repo.sh`; that script now also runs a live-positive canary (a temp file with a ZWSP must
  hit, else exit 3), so a broken detector fails `just audit` and CI. (a) shipped as a pre-commit
  gate only, report-only: `scripts/jscrub/precommit-scan.sh` scans staged blobs and blocks on a
  hit; nothing runs `clean`/`--in-place`. No PostToolUse hook. Wired by `install.sh` through
  `scripts/pre-commit.sh` (session-end check + jscrub). Tests: `tests/test_jscrub_gates.py`.
  Original: **`jscrub` write-side automation** (opened 2026-09-03; read-only half wired 2026-10-22 as
  `just audit` + CI job). Still open, each needing its own pre-mortem: (a) a `PostToolUse` or pre-commit
  gate — `--in-place` and `--follow-symlinks` are the flags to think hardest about before automating
  a tool that rewrites files; (b) `check-vendor` in CI, which now works with no checkout so it can
  actually run there. Also unresolved: with the test fixtures escaped, the repo contains no live
  positive, so a broken detector would not surface via `jscrub audit` — the unit tests are the only
  guard.
- **[NOT FILED 2026-10-23 — already fixed upstream as [jcodemunch-mcp#565](https://github.com/jgravelle/jcodemunch-mcp/issues/565), closed 2026-09-01, shipped v1.108.315]**
  Re-checked against installed 1.108.391: `get_watch_status` now routes each repo through
  `FreshnessProbe.repo_freshness` (`tools/get_watch_status.py:50-72`). The watcher's flag is
  renamed `watcher_flagged_stale` (`:135`), and `any_stale` is set from the measured
  freshness (`:157`). A live call returned `any_stale: true` with one repo `stale` and
  `freshness_checked: true`. The original write-up follows for history.
  Upstream: `get_watch_status`
  reports `any_stale: false` without measuring anything (`jgravelle/jcodemunch-mcp`, verified
  against installed 1.108.288). Staleness is read from `get_reindex_status`, which is **in-process,
  in-memory** state (`tools/get_watch_status.py:73,90`). The watcher runs in the systemd daemon —
  a different PID — so a querying MCP server has no reindex state, `has_any_reindex_state()` is
  False, and every repo takes the hardcoded `{"index_stale": False}` default. `any_stale` then
  answers False having measured nothing, on the normal path rather than an edge case.
  Reproduced 2026-08-21: all 18 repos `index_stale=false` **and** `watched_by_another_process=true`
  (holder pid 1794), including `/opt/proj/Uncle-J-s-Refinery` whose index was behind its tree at
  the time. Upstream already has the fix in a sibling module: `FreshnessProbe.repo_freshness`
  (`retrieval/freshness.py:245`) returns `fresh`/`stale`/`unknown`/`not_tracked`, and its docstring
  describes precisely this — *"a Boolean has nowhere to put 'I could not find out' … the verdict
  then rendered False as `fresh`."* `get_watch_status` is the caller still using the Boolean that
  tri-state was written to replace. **Routing already corrected in CLAUDE.md §1.**
  This resolves the prior "one narrow scan, not an answer" entry: the tri-state exists, the parked
  note attached it to the wrong tool, and the repo-wide re-scan (110 files) found where it lives.
- **Track upstream issue [dwarvesf/claude-guardrails#17](https://github.com/dwarvesf/claude-guardrails/issues/17)**
  (filed 2026-08-15). Until it lands, **re-running `install-guardrails.sh` re-merges the
  buggy template and restores the bug** over `hooks/discipline/push-guard.sh`. If they
  accept the direction, offer the PR — the tokenised implementation and its 41-case
  matrix already exist here.
- **Fast-forward the second clone off `f3a7ed9`.** Its `main` is still pinned there, and
  the ruleset now *rejects* its push rather than letting it destroy `main`. Until someone
  fixes it, expect a confusing push failure on that machine — that failure is the control
  working. Needs access to the other box. Tried 2026-10-22: tc-vmh-03 (Tailscale
  100.94.95.50) timed out on :22, and the Pi has no resolvable name from this host. Next time
  one is up: `git -C <clone> fetch origin && git -C <clone> reset --hard origin/main`, but
  only after checking that `git log origin/main..main` there is empty or already pushed.
- **[DONE 2026-08-21] Ground-truth the jdocmunch v1.126.0 confidence rescale.** Verified against
  installed 1.133.0 (`retrieval/confidence.py:1-45`, `retrieval/verdict.py:37`), and the finding
  contradicts what we had written. The scale was **always 0–1** — nothing was renumbered. The bug
  was `strength` reading a raw score against a hardcoded BM25 curve in every mode, so identical
  ranking quality scored 0.62 lexical / 0.087 hybrid. **BM25 thresholds are byte-identical to
  v1.125.0** (`BM25_CEILING = 12.0` makes `1-exp(-3t/12)` ≡ `1-exp(-t/4)`); only hybrid/semantic
  moved, upward, having been understated. CLAUDE.md §3 said the opposite — that any old threshold
  was wrong and the scale unverified — and is corrected. Same mechanism confirmed in jcodemunch
  1.108.288 (`retrieval/confidence.py:51,110`); §1 corrected to match.
  Route that worked: `index_dependency` against the **import** name (`jdatamunch_mcp`), not the
  distribution name — the `top_level: missing` error is specific to passing `jdatamunch-mcp`.
  jdocmunch was already indexed as a watched dep at `~/.code-index/deps/jdocmunch-mcp@1.133.0`;
  `resolve_repo` on that path returns the handle. The `gh api` route below stays valid but is no
  longer needed for this.
  **The rest of the range was verified the same day** — v1.124.1/#104 (ignored args degrade the
  absence verdict), v1.126.1 (dot-dir rule, narrower than we had written), v1.130.0
  (`corpus_selection_changed`) and v1.132.0 (embedding worker on by default, fail-preserving). All
  four are in CLAUDE.md §3 with source lines. The `9235e22` parked note is fully discharged.
- **The `gh api` route for verifying an installed package against upstream** — fetch via
  `gh api repos/<owner>/<repo>/contents/<path>?ref=<sha> -H "Accept: application/vnd.github.raw"`
  then `diff` against the installed copy. Better than reading `.venv/` when the question is
  whether the *local install* has drifted from upstream, rather than what the installed code does.
- **[DONE 2026-10-23] Dropped the Python-API call for the plain CLI in `run_index_local()`.**
  Now in `scripts/lib/jdocmunch-index-local.sh`, CLI only, tested with a stub CLI. Found on the
  way: the CLI exits 0 on `{"success": false}` (1.149.0), so the old fallback counted a failed
  refresh as reindexed; the verdict is now read from the JSON. Original entry follows.
  **Consider dropping the Python-API call for the plain CLI in `run_index_local()`.** The
  reason it exists — "the CLI exposes no way to pass ignore patterns" — stopped being true
  when upstream #108 added `--extra-ignore-pattern`, `--no-ai-summaries` and `--embeddings`.
  The CLI is already the fallback and already carries all three. The API still buys
  structured JSON in one call, so this is a simplification, not a fix; weigh it on its own.
- **[FILED 2026-10-23 — [jdocmunch-mcp#196](https://github.com/jgravelle/jdocmunch-mcp/issues/196)]**
  `index_local` crashes with `KeyError 'owner'` when given a name colliding with its own
  sidecar namespace (e.g. `X.summary`). Found 2026-08-08. Reproduced on installed 1.149.0 in a
  scratch `DOC_INDEX_PATH`. The crash is at `storage/doc_store.py:1724` (`load_index` reads X's
  summary sidecar as the index). A second symptom of the same cause is silent: `--name X.related`
  succeeds and overwrites X's related-sections sidecar with the new index. Upstream main is still
  unguarded (`_safe_repo_component` checks characters only). Watch #196 for a fix, then drop
  the item.
- **[FILED 2026-08-16 — [jdocmunch-mcp#120](https://github.com/jgravelle/jdocmunch-mcp/issues/120)]**
  jdocmunch's watcher flag gap (`jgravelle/jdocmunch-mcp`,
  `service_installer.py`) — found 2026-08-15. `watch-install` accepts no arguments and
  `_exec_cmd()` hardcodes `[sys.executable, "-m", "jdocmunch_mcp", "watch"]`, while
  `_install_systemd()` rewrites the unit with `write_text()` on every run. There is therefore
  no supported way to pin the watcher's indexing posture, and a hand-edited `ExecStart` is
  silently reverted by the next `watch-install` — which the stack-upgrade routine performs.
  Our workaround is a systemd drop-in under `jdocmunch-watch.service.d/`, which
  `_install_systemd()` does not touch. Retire it only after `systemctl --user show
  jdocmunch-watch.service -p ExecStart` shows the flag coming from the unit itself — not on
  the strength of an upstream release note, which would silently restore
  `use_ai_summaries=True`. Ask for `--no-ai-summaries` / `--embeddings` passthrough on
  `watch-install`. The same
  The embeddings half was deliberately **left out** of the filing, per upstream
  CONTRIBUTING's "one issue, one verdict" — and because the version of it recorded here was
  wrong. `watch` does expose no embeddings flag, but the claim that setting
  `JDOCMUNCH_OPENAI_COMPAT_URL` alone turns `use_embeddings="auto"` ON is **false**:
  `openai-compatible` is not in `_EMBED_AUTO_DETECT_ORDER` and is never auto-selected.
  Corrected in SECURITY.md with the evidence. If the narrower version is worth tracking,
  it needs its own issue.
## Recently completed (2026-10-26 — offload first)

- **agy and Heretic do the work** (PRs #218–#225): task tiers with quota fallback and correct
  reset parsing; `light` goes to Heretic/ask_local first; agy diagnosed its own failures
  (`review/2026-10-26-agy-self-diagnosis.md`) and built the fixes — denied commands named, tool
  tally, failed-run logs copied to `state/agy-logs/`, `just test` works in its sandbox,
  `local-health`, rules for how it lost jobs, `git grep` closed. `just offload` measures it;
  the `self-work-budget` hook enforces it in every project.

## Recently completed (2026-10-25 — delegate by default)

- **`delegate` MCP server** (PRs #203–#206). Every project gets `ask_agy`, `ask_heretic`,
  `ask_openai`, `make_image`, `make_video` and `speak`, and CLAUDE.md makes delegating bounded
  work the default. Local-only guard: `config/delegate-local-only.txt`.
- **agy permissions durable**: `features/antigravity/permissions.json` is the single source.
  It gained the denies for anatomy-lab, gitea secrets and env files. `sync_mcp.py` skips
  `delegate`, so agy can't call itself.

## Recently completed (2026-10-22 — local chat page)

- **Web search in the chat page**: a "Search the web" checkbox feeds the top 5 SearXNG results
  (`/opt/docker/searnx`, `127.0.0.1:8086`) to whichever model answers, with sources listed.
- **`just chat`** serves `http://127.0.0.1:8091` (PR #169): Start/Stop/Logs for heretic, chat,
  and one-click second opinions from Claude (`claude -p`, hooks disabled) or agy.

## Recently completed (2026-10-22 — ask_local on the abliterated model)

- **Qwen3.6-35B-A3B Heretic is this host's `ask_local` model.** It runs on llama-server
  (`docker/llama-heretic/compose.yaml`, `just heretic up -d`) at about 40 tok/s with 4.8 GB of
  VRAM. Against `qwen3.5:9b` it got 5/5 vs 4/5 on classification, tied on extraction and code,
  and answered a lock-picking prompt that the 9B model refused. `ask_local` gained an `openai`
  backend; the repo default stays Ollama.

## Recently completed (2026-10-22 — the "work I can just do" sweep)

- **Guards:** grep-guard resolves symlinks and judges each path; push-guard follows bash quoting
  (what bash would execute, incl. `"$(git push)"`, `bash -c`, `eval`, pipes into a shell);
  surface-write-guard catches end-of-command redirects and GNU `sed -i`, and `cp` inside `mcp`
  no longer false-matches; credential-guard is wired on Windows.
- **Hook log:** guards write `state/hook-blocks.log` as text (control bytes stripped) and archive
  it past 1 MiB, never truncating.
- **Automation:** healthcheck + session start flag local `main` commits the remote lacks;
  post-merge reindexes on any code change; the 07:00 check reindexes once before reporting
  stale; the doc gate fires only on real `git commit` in this repo; the 03:00 agent reads
  installed packages via `index_dependency`; `test_skills.py` reads UTF-8.
- **Install:** jdocmunch-watch drop-in provisioned by `install-reliability.sh` and doctor
  `--fix`; doctor `mcp-scope` covers all five servers; `just install-gate` runs the real
  `install.sh` in a clean Debian container with a stub `claude`.
- **Scout:** idempotent Telegram send, run lock, one message a day, `run done` health line,
  library finds routed to `library-backend-adoption-eval`, §10 gh facts logged.
- **pysqlite3 wheel** rebuilt manylinux2014 (imports on Debian 11 / glibc 2.31).
- **anatomy-lab** gets a private GitHub push mirror (Bill's call).
- **Gitea tokens:** 15 one-shot tokens (ids 5–15, 17, 18, 21, 35) revoked after Bill accepted
  the 3 MEDIUMs. Backup taken, `integrity_check` ok before and after, backup deleted. Kept:
  1, 2, 4, 27.
- **Remote-less repos:** larder, patentengine, reciepts, tao-intel and jaredrhod now have
  private Gitea repos, with no GitHub mirror. Local history was imported by PR.
- **Upstream:** dwarvesf/claude-guardrails#20 filed.

## Recently completed (2026-10-17 — repo scout and skill library)

- **Repo scout** (PR #135, cron installed 04:15): a capability map plus one Telegram find
  each morning, and a three-yes ladder from find to trial. The map is awaiting Bill's
  review. Design: `docs/superpowers/specs/2026-10-17-repo-scout-design.md`.
- **Skill library** (PR #137): `just skill-lib sync|list|add` keeps whole collections in
  `../skill-library`, loaded by nothing. astropy, markitdown and timesfm-forecasting are
  vendored from K-Dense-AI/scientific-agent-skills.

## Recently completed (2026-10-17 — live build view, credential guard, Partikus MCP)

- **live_preview** (#133): a live browser view of any build for any project. Its viewer
  comes from the HKUDS/CLI-Anything review. An independent review found a stored-XSS HIGH,
  fixed before merge.
- **credential-guard** (#134): no tool touches credential files, reads included. Bill
  asked for it.
- **Partikus MCP server** (partikus #39): an agent builds parts through one persistent
  offscreen FreeCAD worker, and every step shows up in live_preview.

## Recently completed (2026-10-15 — referee and media-teardown)

- **Cross-provider referee** (`scripts/referee.py` + `referee` skill). Gemini judges Claude's
  work through agy and returns a JSON verdict; anything but a well-formed verdict exits 1.
- **`media-teardown` skill.** Six-part output with required slots for source vs spin and
  omissions, the two parts the no-skill baselines left out.
- **`verifiable-task` skill.** Write the check before delegating, run it yourself, report
  what it measured. Six no-skill baselines on Claude (Opus and Haiku) already did this, so
  the skill is aimed at the weaker agents the skills are portable to (agy, local, Codex).

## Recently completed (2026-10-15 — skills portable; Antigravity gets the stack)

- Skills: 9 vendored from mattpocock/skills, 3 local-only skills and the adversarial-review
  workflow backed up, `~/.agents/skills` + `~/.gemini/skills` linked, `docs/SKILLS.md`
  generated (PRs #114–#117).
- Antigravity CLI: installed, signed in, read-only permissions, `ask_agy.py`, 8 MCP servers,
  routing policy include (PRs #118, #119). Verified live.
- Healthcheck 9a parses YAML; 8 skills fixed for strict harnesses (PR #116).
- Stack lockfile committed after review (PR #120). Dictation into any window (voice-line #10).

## Recently completed (2026-10-12 — clean-room-rebuild skill and an OS-level wall)

- `clean-room-rebuild` global skill adopted (#106, #107) and REA reviewed (safe; MIT; no telemetry).
- Wall hygiene (#108): `scripts/clean-room-investigator.sh`, memweave exclusion by the
  `.clean-room-investigator` marker, and the `check_clean_room_wall` healthcheck.
- OS-level isolation (#109), after a Codex review showed profiles only scope discovery. The
  healthcheck now also fails if REA is installed in the account.
- Upstream pitch filed: morluto/rea#2187 and #2188.

## Recently completed (2026-09-01/03 — `review/` triaged; `jscrub` extracted and hardened)

- **`review/watermarks-remover` needed no conversion — it was already a finished plugin** (MIT,
  v0.6.0, HEAD `be38ccc`): two Claude skills, a marketplace manifest, a `PostToolUse` hook, a
  pre-commit hook, a Docker service, ~60 tests. The real gap was **three** CLIs with three flag
  vocabularies, `clean_file.py:30-263` being one 234-line `main()`.
- **`scripts/jscrub/` ships the hygiene half as one DRY CLI** — `inspect` / `clean` / `audit`, every
  flag declared once in an option table that argparse, `--help` and the engine kwargs all derive
  from. Three-way exit code (0 clean / 1 findings / 2 unscannable, worst wins) so a CI gate can tell
  "scanned it" from "never looked". PR #140.
- **Layer B was deliberately left behind.** Upstream also defeats C2PA/SynthID provenance and ships
  a `stealer/` module that reconstructs a target model's watermark scorer. `jscrub` is text hygiene —
  characters that break tooling — not a way to make AI output unidentifiable as AI output. Keep that
  line if the tool is extended.
- **The drift check no longer depends on the queue it came from.** `check-vendor` compared against
  `review/watermarks-remover`, which is gitignored *and* sits in a queue whose items move to
  `reviewed/` — so it was going to break with `upstream file not found` and could never run in CI.
  Now split into two claims with different evidence: `check-vendor` (pinned sha256, no checkout)
  proves "unmodified since vendoring"; `check-vendor PATH` additionally proves "still matches
  upstream". A passing no-args run is **not** evidence upstream hasn't moved. PR #141.
- **First lint this code has had** (`ruff` absent from the host, no `ruff.toml`; run via `uvx`).
  `PLE2515` caught the hygiene tool carrying literal zero-width characters in its own test fixtures —
  the reason `jscrub audit scripts/` had been reporting its own test file as the tree's only hit.
  Now `chr(0x200B)`; 35 tests, ruff clean, self-audit clean at 55/55.

## Recently completed (2026-08-28 — the 07:00 alert had been crying wolf for 26 days)

- **The nightly healthcheck alert never passed.** `state/healthcheck-notify.log` records a failure
  notification on every scheduled 07:00 run from 2026-08-03 to 2026-08-28 — twenty consecutive
  alerts, zero passes; the only pass in the file is a manual 14:19 run on 08-08 right after a
  hand-repair. The real four-issue mornings (08-23, 08-28) were indistinguishable from the noise.
  Cause was cron ordering: reindexers at 01:00/01:30, the maintenance agent commits at ~03:05, so
  every agent commit missed that night's reindex by two hours and self-healed ~22h later.
  `auto-maintain.sh` now reindexes after its own commits; the crons stay as the safety net. PR #136.
- **`healthcheck-notify.sh` logged the failure count but not the names**, so the twenty failures
  could not be told apart after the fact — the only copy of that detail went to Telegram. Now
  logged per check. Verified against a canned run containing a fake `sk-lf-` key that no secret
  reaches the log: `$FAILURES` holds `bad()` output only, and `healthcheck.sh:704` sends its
  matched credential lines to stderr without the `X` prefix.
- **`uv.lock` had recorded none of the last three upgrades.** HEAD pinned `jcodemunch-mcp 1.108.235`
  / `jdatamunch-mcp 1.29.1` / `jdocmunch-mcp 1.121.1` against a venv running `1.108.303` / `1.31.7`
  / `1.136.1` — a clean `uv sync` from HEAD would have downgraded the whole stack, `search_ast`'s
  empty-table window (#553) included. Committed alone, since `auto-maintain.sh` rightly forbids
  folding it into a per-package commit; `commits_behind()` reads it from disk, so nothing was
  disarmed while it sat dirty.

## Recently completed (2026-08-16 — the workaround outlived the bug)

- **Prune-compensation shim deleted** (PR #123). Upstream #102 fixed the `lstrip("./")` bug
  on 2026-08-07; we kept compensating for it for nine days because nobody read the tracker.
  Confirmed fixed by re-running the issue's own repro against our pinned version — both the
  gitignore path and the `SKIP_PATTERNS` path prune correctly with no compensating patterns.
  Only the dead block went: the `forced_ignore` loop that keeps credential-bearing files out
  of the corpus and the raw mirror is untouched, and was re-verified by a live reindex.
- **Upstream [#120](https://github.com/jgravelle/jdocmunch-mcp/issues/120) filed** for the
  `watch-install` flag gap, and a **false embeddings claim in our own SECURITY.md corrected**
  (PR #122) — `openai-compatible` is never auto-selected, and upstream's opt-in gate predated
  our claim by six days.

## Recently completed (2026-08-15 — controls that existed but nothing verified)

- **`surface-write-guard.sh` versioned + its logging fixed** (PR #120). It was never silent:
  `head -c 200` truncates bytes not lines, so one multi-line block wrote four physical lines
  with `session=` stranded on the last. 401 of 3832 lines are continuation junk. Also closed a
  worse defect found while porting — a missing `jq` made the guard `exit 0`, silently allowing
  every command it screens.
- **Two probes for controls nothing was checking** (PR #121). `check_jdocmunch_watch_posture`
  asserts the watcher's *effective* `ExecStart` carries `--no-ai-summaries` (not that the
  drop-in file exists, so upstream passthrough landing does not turn it red).
  `check_vault_hook_registered` asserts the vault Stop hook is still wired.
- **Vault checkpoint Stop hook** (PR #119) — daily note exists, carries a `## Session N` entry
  from this session, vault tree clean. Date comes from the transcript, not the wall clock, so
  midnight-spanning sessions don't false-fire.
- **The local-only doc-corpora invariant is in SECURITY.md** (PR #118), with all three call
  sites named and the embeddings-egress residual recorded.

## Recently completed (2026-08-14 — `origin/main` force-reset: cause, control, detector)

- **The 12 lost commits are re-landed** (PR #108). `origin/main` and local `main` are
  converged; `3f70ec2`, previously on one disk, is reachable from `origin/main`.
- **The cause was identified, after three sessions of calling it unexplained.** Not three
  occurrences but **five** — `f3a7ed9` pushed on 2026-08-04, 08-07 (×2), 08-09 and
  08-14T11:23Z, the last four minutes before PR #107 merged. Writer: a second clone pinned
  at that commit. Found via `git reflog show origin/main` (`forced-update` at `@{2}`/`@{8}`)
  cross-referenced with GitHub push-event `head_sha`. Every prior fix re-landed content
  without touching the write path that removed it.
- **`main` is protected** by ruleset `protect-main-no-force-push` (id `20854165`):
  `non_fast_forward` + `deletion`, no bypass actors, owner included. The repo previously
  had no protection and zero rulesets.
- **Regression detector added** (PR #109) — `scripts/check-origin-main-regression.sh`,
  run from the SessionStart hook, verifying the outcome the ruleset guarantees. Signal is
  non-fast-forward, **not** "local ahead of remote". 10 tests + their own CI job.
- **Two instruments were shown to lie** across all five wipes: `gh pr list` reports
  force-pushed-away PRs as MERGED, and `git branch -a` listed a remote-tracking ref for a
  branch `ls-remote` shows does not exist. **`ls-remote` is the only authority.**

## Recently completed (2026-08-13 — grep-guard `~` paths + hook-blocks log integrity)

- **`grep-guard.sh` denied `~`-prefixed source outside the repo** (PR #106). The guard
  receives the raw unexpanded command string, so `~/…` never arrives as `/…` and the
  out-of-repo exemption (`== /*`) missed it — the same file was blocked by one spelling
  and allowed by the other. `~` is now expanded to `$HOME` before the containment test,
  matching the recursive branch.
- **Multi-line blocked commands corrupted `state/hook-blocks.log`** (PR #106). `head -c`
  truncates bytes, not lines, so one command wrote N rows and only the last carried
  `session=`. 385 of 3452 lines were continuation junk — the real entry count was 3067.
- **Weekly hook-blocks review completed** for 2026-08-13: 33 entries, 23 ALLOWED / 10
  BLOCKED, 9 of 10 blocks confirmed as the guards working correctly. The tenth is
  permanently undiagnosable because the 120-byte truncation cut away the trigger.

## Recently completed (2026-08-08 — MCP scope shadowing + reindex sidecar)

- **All five stack MCP servers restored on Linux** (PR #105). The Windows port's
  committed project-scope `.mcp.json` (`C:\...` commands) shadowed the user-scope
  registration per server name — the missed second half of the PR #103 damage.
  Unshared: moved to `scripts/win/mcp.json`, `/.mcp.json` gitignored, docs updated.
  One-time Windows follow-up: `cp scripts/win/mcp.json .mcp.json`.
- **Nightly jdocmunch reindex no longer fails on phantom `.summary` repos**
  (PR #104). The 2026-08 jdocmunch writes a `<name>.summary.json` sidecar that the
  drift scanner's `SIDECARS` allowlist predated → `KeyError 'owner'`, exit 1.

## Recently completed (2026-08-04 — stack upgrade applied)

- **Stack upgrade landed**, further than planned: jcodemunch 1.108.235 (not .204),
  jdatamunch 1.29.1, jdocmunch 1.121.1 (not 1.120.0). Ran `uncle-j-auto-maintain` by
  hand — same code path as 03:00 — because `uv sync` cannot run from inside a session
  on this host. Lock and sync moved together; `uv.lock` committed in `05722de`.
- **The `uv` cache-retry guard fired in production for the first time** and recovered:
  stale `pysqlite3` cache entry → cleared 1.1 GiB → retry succeeded.
- **Prune shim confirmed on 1.121.1** — `prune compensation` fired on a forced reindex,
  and `unavailable` has never appeared in the log. Closes the 2026-07-31 open question.
  Caveat: the nightly reindex skips when the repo is at HEAD, so it only got exercised
  because a commit moved HEAD.
- **Breaking-change detection fixed** (`54fc502`) after it missed jcodemunch v1.108.208
  removing `content_hash` from `get_symbol_source` responses, while its only hit in 239
  commits was `unbreaking CI lint`.

## Recently completed (2026-07-30/31 — Windows port + silent-failure closure)

- **The Windows port** (sessions 1–3): Task Scheduler jobs replacing cron, `jq`
  and `uv` on PATH, `serena` + `duckdb` registered, four dead hook guards
  revived, and the nightly jdocmunch reindex unfrozen. `HEALTHCHECK: ok`, and
  the 01:00/01:30 jobs verified running unattended.

## Recently completed (2026-06-29 — jMunch Console integration)

- **jMunch Console integrated (light):** `scripts/jmunch-console.sh` launcher; `check-stack-freshness.sh` now tracks
  jmunch-console clone freshness + shows upgrade hint. Usage: `bash scripts/jmunch-console.sh` → `http://127.0.0.1:8765`.
  Phase 2 wiring (healthcheck entry) deferred until stable over a few sessions.

## Recently completed (2026-06-24 — uv-sync recovery + install.sh memweave-venv gap closed)

- **Recovered a machine from a stray plain `uv sync`** (no `--inexact`): it wiped `.venv`
  site-packages — langfuse, the §2b pysqlite3 swap, and the retired mempalace/chromadb deps.
  Restored langfuse + the swap, built `.venv-memweave` + memory index, registered the
  `uncle-j-memweave-sync` cron, installed the `jcodemunch-watch` unit. `HEALTHCHECK: ok`.
- **`install.sh` §2c — provisions `.venv-memweave`** (PR #83): closes the gap where the
  installer never created the 3.12 memweave venv, so memory sync + the Stop hook died on any
  machine that hadn't built it by hand.
- **Mempalace fully retired:** removed the 6 stale `uncle-j-mempalace-*` crons (their scripts
  were already deleted) + untracked `mempalace.yaml`/`entities.json`. (Repo was already decommissioned.)
- Committed the jcode/jdata/jdoc `uv.lock` bump + rebuilt vendored pysqlite3 wheel.

## Recently completed (2026-06-16 — healthcheck loop fixed + pin-canary direct Python)

- **4 healthcheck bugs fixed:** MCP not-Connected hint no longer triggers install.sh; Langfuse
  checks gate on `LANGFUSE_PUBLIC_KEY` so unconfigured machines skip silently; 3 feature-specific
  crons removed from mandatory EXPECTED array; pin-canary hint restored to interactive `run:` form.
- **`scripts/pin-canary.sh` rewritten:** now calls `capture_canary()` directly via `.venv/bin/python`
  from `jcodemunch_mcp.retrieval.embed_drift` — no `claude` binary, no MCP session required.
  Removed the `CLAUDE_CODE_SESSION` guard and `claude -p` approach entirely.

## Recently completed (2026-06-15/16 — git pull self-healing)

- **PR #77 merged:** `install-reliability.sh` prunes stale `~/.claude/skills/` symlinks on re-run;
  `scripts/post-merge-hook.sh` auto-runs `install-reliability.sh` when `global-skills/` or the
  installer changes. `git pull` is now the one command — no manual re-run needed for skill changes.

## Recently completed (2026-06-14 — cron silent failures + healthcheck runtime probes)

- **3 silent cron failures fixed:** `dream.sh` PATH export (dreaming broken since Jun 10 — cron
  couldn't find `claude`); `state/dreaming.env` unquoted cron schedule (bash parsed `2 * * *` as
  a command on every source); `auto-maintain.sh:294` `${#SKILL_NAMES[@]:-0}` invalid bash
  (bad substitution on every run). Healthcheck added `check_dreaming_runtime` (last-run freshness
  >36h = FAIL, surfaces `!!` log clues) + `check_auto_maintain_runtime` (shell error pattern scan).

## Recently completed (2026-06-14 — follow-up sweep + Telegram incident)

- **Telegram red-team depth findings closed (PR #73):** whole-file injection scan on `promote`
  (frontmatter included), `assert_skill_target_safe` removes the destructive `rmtree`, output
  redaction gains relative-`.env` + spaced-`sk-ant` patterns (+ left-boundary fix on the existing key rule).
- **getUpdates single-consumer — 22-day offset-freeze incident (PR #74):** two cron pollers consumed
  one bot token; made the gateway the sole consumer (approve/skip relayed via
  `state/stack-alerts-callback.json`), + F4 log byte-sanitize, F5 datetime tz-aware, per-poll
  observability line. **Freeze resolved live** by repointing the corrupt offset into the real id range.
- **Drain helper hardened + `--catch-up` (PR #76):** removed the negative-offset footgun (it
  confirmed/ate a live test DM); dry-run is now genuinely read-only; `--catch-up` repoints to the
  oldest unconfirmed id so queued messages are answered, not skipped.
- **healthcheck probes (PR #75):** `jcodemunch-watch` daemon liveness (warn-not-fail under cron) +
  memweave index freshness (<48h).

## Recently completed (2026-06-13/14 — security & retrieval hardening)

- **memweave corpus de-noised (PR #71):** skill invocations inject the skill's full body as a
  user-role turn (`Base directory for this skill:`), which the exporter indexed as searchable
  prose — flooding prior-art search with stale (often superseded) skill copies. `iter_turns` now
  drops these; `export_project` made authoritative (deletes a stale `.md` when a session falls
  below `min_chars` after filtering). Corpus rebuilt from scratch (577 indexed / 7746 chunks);
  transcripts untouched. Also committed the `jdocmunch-mcp` 1.70.2→1.71.0 autofix `uv.lock` bump.
- **Telegram restricted-agent lockdown (PR #68):** red-team found a CRITICAL — the restricted
  (untrusted) agent ran `claude --dangerously-skip-permissions` with no tool restriction, so a
  prompt injection could read `.env`/host files and exfiltrate out-of-band. Fixed via tested
  `build_claude_argv()` (no skip-perms / `--strict-mcp-config` / `--disallowedTools`); `/work`
  agent unchanged.
- **jcode watch daemon + grep-guard hardening (PR #69):** activated the `jcodemunch-watch` user
  service (real-time index freshness across all 9 repos); rewrote `grep-guard.sh` to route ALL
  source-code reads (not just `grep -r`) to jcodemunch via per-segment dispatch.
- **understand-anything plugin enabled in project settings (PR #67).**

## Recently completed (memweave migration — fully closed 2026-06-13)

- **LIVE residue scrub (PR #63):** repointed 18 global skills + feature docs + PORTING.md + flowchart
  + GEMINI.md off mempalace → memweave; deleted dead recall-bench + `CLAUDE.md.merged` + `entities.json`.
- **jmunch stack upgraded to HEAD (PR #64):** jcode 1.108.55 / jdata 1.13.1 / jdoc 1.70.2; cleared
  `stack-not-at-head`. (Restart Claude Code to load the new MCP servers; run
  `post-upgrade-mcp-integration` next session.)
- **Audit-sink repoint (PR #57) + `post-audit-mempalace-capture`→`post-audit-memory-capture` (PR #62)**
  + global `~/.claude/` edits applied at the keyboard. The migration (PRs #45–#64) is complete in-repo
  and in global config; mempalace fully decommissioned.
- *(obsolete — mempalace gone)* ~~Upstream MemPalace PR #1607~~ / ~~turbovecdb parallel eval~~.

**Only genuinely-remaining deferred item:** purge the staged trash dirs (2.4 G + 55 G, irreversible —
Bill's call). See HANDOFF + `project_memweave-migration-done`.

## Planned

**Improvement Program** (spec: `docs/superpowers/specs/2026-06-11-refinery-improvement-program-design.md` — phases in order; principles: deterministic-first, local-canonical):

- **Phase 2 — Accuracy instrumentation → memweave migration** ✅ **DONE 2026-06-13** (see Completed). Backend decision (MemPalace eliminated → memweave) resolved 2026-06-12; memweave built (PRs #45–#48) and the full migration + mempalace decommission shipped (PRs #50–#55).
- **[DONE, rescoped 2026-10-23] Phase 3 — Local rail.** ask_local (Heretic on llama-server, per
  `config/ask_local.env`) already is the local endpoint, and the lineup work picks the model,
  so the endpoint/hardware-detect half is dropped. Shipped the missing piece:
  `scripts/local_rail.py`, a content-hash cache (sha256 of backend, model, system, prompt and
  params; errors never cached; atomic writes) that batch jobs call local-first. Wired into
  the guide benchmark and the Telegram daily summaries. Not done: mine compression (no
  consumer) and dream synthesis (it writes boot-loaded CLAUDE.md playbooks, too risky for a 9B
  model unreviewed). Tests: `tests/test_local_rail.py`. Original:
  **Phase 3 — Local rail** — Ollama endpoint + hardware-detect model select (Qwen3-Coder 30B / Devstral 24B / Qwen3 8B tiers); batch pipelines local-first (mine compression w/ content-hash caching, dream synthesis, guide compression); dreaming now promotes into the memweave store; pattern-importance scoring as pure script
- **Phase 4 — Subtraction & absorption** — signed-off deletions (Bill, 2026-06-11): ~~D1 stale palace copies (55GB)~~ executed 2026-06-11; ~~**D2** ChromaDB repair apparatus~~ **DONE 2026-06-13** (mempalace fully decommissioned, PRs #50–#55); **D3** ralph — only if Phase 2 usage counter confirms idle. **[2026-10-23] Not removed:** the Phase 2 counter never measured ralph (`benefits.json` lists it under `missing`), so it can't confirm idle. No ralph cron is installed. Added the counter: `ralph-harness.sh` now appends to `state/ralph-runs.log` and `collect_benefits.py` reports it; decide after a few weeks of data. **[DONE 2026-10-23] CLAUDE.md de-dup:** `.claude/settings.json` `claudeMdExcludes` skips the repo copy (and worktree copies) here, so sessions load the policy once from `~/.claude/CLAUDE.md` (~5.1k tokens saved per session). The repo copy stays the deploy source; install.sh/doctor are unchanged, so the global Dreaming Notes tail is preserved. Original: CLAUDE.md de-dup (project stub, ~4k tokens/session); absorption check added to `post-upgrade-mcp-integration` (script-diff Claude Code changelog vs harness-layer manifest)

- **[DONE 2026-10-23] Compressed `jcodemunch_guide`** — benchmark run on an idle host, 20
  routing queries on Heretic: full 738 tokens 18/20, compact 184 tokens 18/20, LLM-compressed
  660 tokens 18/20. The plain cut wins (75% fewer tokens, same accuracy); LLM compression is
  dropped. Filing the upstream patch is Bill's call (it's a public PR on jgravelle's repo).
  Earlier note: measured: the guide is now 2,804
  chars (the 4.6–5.1k-token estimate is stale) and nothing here loads it per session. The
  catalogue is 76% of it and duplicates the MCP tool list, so a deterministic `compact` cut
  (680 chars) beats LLM compression. Built `scripts/guide_bench/` (20 routing queries, local
  model as router) and an upstream-ready patch (`docs/proposals/2026-10-23-jcodemunch-guide-compact.patch`).
  **Not done:** the benchmark run (Heretic at ~0.6 tok/s under host load, two timeouts) and the
  upstream filing (Bill's call). Details: `docs/proposals/2026-10-23-compressed-jcodemunch-guide.md`.
  Original: **Compressed `jcodemunch_guide` return value** — offline compress `_generate_claude_md_snippet()` output via cheap model (Phase 3 local rail candidate); benchmark 20 representative routing queries before/after; ~4,600–5,100 tokens/session savings at full tier; upstream contribution to jcodemunch

- **[DONE 2026-10-23] ralph-harness env-strip** — `ralph-harness.sh` unsets both keys after its
  CLI check; the Telegram gateway passes a filtered `env=` to its `claude` subprocess. Tests:
  `tests/test_env_strip.py`. Original: **ralph-harness env-strip (after 2026-06-15)** — strip `ANTHROPIC_API_KEY` + `ANTHROPIC_AUTH_TOKEN` from subprocess env in `ralph-harness.sh` and Telegram gateway; enables Agent SDK credit billing ($0 actual cost within monthly credit); do NOT apply before June 15

- **[DONE 2026-10-23] Telegram chat history persistence** — the skill's design, with memweave as
  the long-term store: every exchange (post-redaction) goes to `state/telegram-history.jsonl`; the
  last few turns (≤6, ≤6 h, ≤3,000 chars, re-redacted) are prefixed to each new message; the
  nightly memweave sync has the local model write `telegram-YYYY-MM-DD.md` summaries (never raw
  turns) into `~/.uncle-j-memory/memory/`. `scripts/lib/tg_history.py`, three lines in the
  gateway, tests in `tests/test_tg_history.py`. SQLite was skipped: JSONL plus the memweave
  corpus already cover it.

- **[DONE 2026-10-23] Agent harness competitive analysis** — `docs/2026-10-23-competitive-analysis.md`
  (ECC, superpowers, Hermes, ruflo, plugin marketplaces; stars and claims as of that day). Open
  gaps it names: install reach (plugin packaging), multi-host, one chat surface.

- **[RESOLVED, closed 2026-10-22] jdocmunch `.summary` sub-indexes report 0 sections** — not
  indexes at all: `.summary.json` is a jdocmunch sidecar that the healthcheck read as a repo.
  `cb45dae` (2026-10-05) added it to the sidecar list (healthcheck.sh SIDECARS); no warning since.
  Original: (surfaced 2026-07-23) — healthcheck
  warns for both `Uncle-J-s-Refinery.summary` and `proj-fog-of-chess.summary`. Non-blocking.
  Determine whether the summary index is genuinely unpopulated or the count is misreported;
  the latter would be the same class of counting bug as the 2026-07-19 `ls | wc -l` fix

- **[DONE 2026-10-23] ECC specialist agents** — evaluated: keep `code-reviewer` (with
  `silent-failure-hunter` merged in, shell/subprocess patterns added, JS-only sections cut,
  read-only jcodemunch tools granted). Dropped `planner`, `architect`, `tdd-guide` and
  `security-reviewer` (they duplicate superpowers skills or red-team/blue-team, carry a JS/SaaS
  stack, and the reviewer had Write/Edit). One line each in `docs/RELIABILITY.md`.
  install-reliability prunes the dangling links; healthcheck checks whatever ships.

- **[DONE 2026-10-23] Expand discipline hook surface list.** Reviewed `hook-blocks.log`
  from 2026-05-25 on: 513 edit-surface blocks, 7532 allowed. Narrowed: test modules
  (`tests/test_*.py`, `*_test.py`) were 65 blocks (13%); conftest.py and guard dirs stay
  gated. Widened: `.mcp.json` (the PR #105 incident), `settings.local.json`, `justfile`,
  `*.service`, `*.timer`. Extensions now compare case-blind, and a symlink resolving onto a
  surface is gated. surface-write-guard mirrors the additions.
- **Open: surface-write-guard can't see shell variables.** 43 of 102 blocks since 2026-10-16
  are writes to `$S/x.py` with `S=/tmp/…scratchpad`. That guard matches regexes, so the fix
  is grep-guard's lexer (or a shared one) in front of it.

- **[DONE 2026-10-23] Telegram gateway, remaining red-team findings.** (a) and (b) were only
  half closed by PR #73. (a) Frontmatter keys that grant power (`allowed-tools`, `hooks`,
  `context`, `agent`) and `` !`cmd` `` bodies are now rejected. Zero-width, bidi and
  fullwidth obfuscation is normalised before the injection scan. (b) An existing skill dir
  with a different SKILL.md was overwritten by `copy2`, and any symlink counted as
  gateway-owned. Both are refused now; an identical SKILL.md (auto-maintain Part C) still
  installs. (c) Added token-shape rules (Telegram, GitHub, OpenAI, Langfuse, AWS, Slack,
  Google, JWT, PEM, Bearer), prose and lower-case key names, and output-only `~/`, Windows,
  MSYS and relative paths. (d) The bot token goes to curl as `-K -` config on stdin in all 6
  call sites, and a malformed token is refused.
- **[DONE 2026-10-23] grep-guard quote-blind tokenizer + session-cwd-only paths.** A
  bash-aware analyzer (an inline python3 lexer) now feeds the judging helpers. It handles
  quoting, `$( )`, backticks, `<( )` and heredocs. It tracks cd/pushd, subshells and literal
  `VAR=value`, and unwraps sudo/env/xargs/find -exec/sh -c/eval. The legacy splitter stays as
  the fallback. Residual: interpreters (`python3 -c open(…)`), `git show`, and file names
  produced at run time (`cat $(git ls-files)`).

- **[DONE 2026-10-22] jcodemunch skew probe** — healthcheck `running processes match the
  installed version` warns on any jcodemunch/jdocmunch watcher or MCP server that started
  before its package's dist-info was written. First run caught the watcher on pre-03:00 code
  (restarted) and a 26 h mafski session's server. Original entry follows.
  The *alignment* half of this item is **done**, and was already
  done when this entry was last read. Verified 2026-08-21: `~/.claude.json` points
  `jcodemunch.command` at `/opt/proj/Uncle-J-s-Refinery/.venv/bin/jcodemunch-mcp`, the same
  binary the reindex writes with (1.108.287), so writer == reader and the
  `sqlite_future_version` fallback cannot recur from this cause. What remains is only the
  **probe**: a `healthcheck.sh` check comparing the reindex-writer version against the MCP
  server binary, so a future re-skew is caught at session start rather than on the first
  failed query. (Original root-cause 2026-07-06, PR #91 HANDOFF.)

---

## Completed (recent)

| Date | Item |
|------|------|
| 2026-07-30 | **Stack ported to Windows 11 + Git Bash** (uncommitted). All three jMunch servers `√ Connected` via project-scoped `.mcp.json` (their CLIs are *not* uniform — jdatamunch takes no args, jdocmunch has no `--transport`); hooks routed through `scripts/win/hook.sh` because `bash` is off-PATH and direct invocation drops shell redirection; `.venv/bin`→`Scripts` compat symlink self-healed on SessionStart since `uv sync` destroys it. `healthcheck.sh --quick` 21 → 8 fails. **Three latent non-Windows bugs found:** `flock` absence made five lock guards fail *open* (reindex logged `OK` while indexing nothing; Telegram gateway never polled), the checkpoint hook's hardcoded root comparison meant it never fired on any platform, and `check_sqlite_version` asserted an exact version so a newer/safer SQLite failed. `tg_security.py`'s module-scope `import fcntl` had been breaking `pytest` collection for the whole suite (+71 tests). Remaining 8: 7 crons (no `crontab`), `features/` extras, serena/context7/duckdb. See `docs/WINDOWS-PORT.md`. |
| 2026-07-05 | **grep-guard false positives narrowed** (PR #89). Three over-broad patterns fixed from real `hook-blocks.log` entries: hyphenated words (`-MORTEM`, `-opt-proj-…`) matched as `-r` flags → token-anchored flag detection; grep pattern args (`"ytd\.sh"`) matched as file operands → pattern/flag tokens skipped; recursive branch ignored the out-of-repo allowance → path-operand walk. Closes the `~/.uncle-j-memory/` reads item. +13 test regressions (40/40); code-reviewer caught a numeric-pattern MEDIUM pre-merge. |
| 2026-06-13 | **pysqlite3 3.51.3 wheel vendored + "duckdb" healthcheck bug root-caused** (PR #65). The recurring `mcp-servers-down(duckdb)` fail was a checkmark codepoint bug (`✓` U+2713 grep vs `✔` U+2714 output) matching zero servers → headlined `missing[0]`=duckdb; fixed to `[✓✔]`. Vendored the pysqlite3-3.51.3 wheel (`scripts/build-vendored-pysqlite3.sh` → `vendor/wheels/`), marker-conditional pin in `pyproject.toml` (PyPI fallback off-platform), `check_sqlite_version` healthcheck assert. Ends the `uv sync` clobber dance permanently. |
| 2026-06-13 | **memweave migration complete — mempalace decommissioned** (PRs #50–#55). 2b-2 freshness cron + Stop-hook; 3b project CLAUDE.md routing → `mw_search.py`; 4a cross-project corpus (`--all-projects`); 4b decommission (scripts/crons/MCP/probes removed, palace staged not deleted, dreaming + 3 global skills repointed); 4c in-repo residue (dead `check_mempalace`, 6 obsolete repair skills, RELIABILITY scrub); 4d removed mempalace/chromadb deps from pyproject/uv.lock; 4e docs sync (README/STACK/ROADMAP + mcp-clients templates). Memory is now offline cross-project memweave (`~/.uncle-j-memory`). Deferred: global `~/.claude/` edits (harness-denied), control-invariant audit-sink repoint, trash purge. |
| 2026-06-11 | Improvement Program Phase 1 — pay-for-itself audit (PR #38): deterministic collectors + scorecard + judgment. KEEP: jmunch-retrieval (5,300:1 payoff), guardrails (315 blocks), langfuse, telegram. FIX: routing-policy (9k tok/session), mempalace storage (0.32 maint share), reliability, skills (prune), dreaming + ralph (instrument). D1–D3 deletions signed off. |
| 2026-06-06 | `dcup` Docker port registry — SQLite registry, flock mutual exclusion, live-reality preflight, sweeper service, PreToolUse hook; 26 projects registered |
| 2026-06-06 | `adversarial-review` skill + workflow — MAD framework (Paranoid/Archaeologist/Pedant/Cynic), 2 debate rounds, judge synthesis |
| 2026-06-06 | `smart-review` skill — rules floor + shadow classifier + drift audit; replaces manual effort-level selection |
| 2026-06-10 | F-04 closed — `healthcheck.sh` `check_mempalace()` now runs both `PRAGMA quick_check` (B-tree) and FTS5 `integrity-check` (inverted-index data layer) as complementary probes |
| 2026-06-10 | ARCHAEOLOGIST-R2-1 closed — post-upgrade SKILL.md step 8 clears `state/post-upgrade-needed`; `session-start-autofix.sh` section 0 warns if flag exists from a prior session |
| 2026-06-10 | PEDANT-R2-1 closed — `auto-maintain.sh` Telegram notification now includes per-package commit range (e.g., `jcodemunch-mcp (abc1234→def5678)`) |
| 2026-06-10 | jragmunch-cli evaluation — verdict: adopt env-strip billing pattern in ralph + Telegram gateway after 2026-06-15 (Agent SDK credit launch); skip review/sweep/changelog verbs (redundant with existing stack) |
| 2026-06-10 | CI test job for `session-end-check.sh` — `test-session-end-check` job added to `ci.yml`; 10 tests (pre-commit + stop-hook modes), 0 API calls, runs on ubuntu-latest |
| 2026-06-10 | Stop-hook session mining — `.claude/settings.json` Stop hook now routes through `scripts/mempalace-mine-convos.sh`; adds HNSW pre/post guard, flock dedup, `--wing conversations` consistency with cron; eliminates dirty-context window |
| 2026-06-10 | post-upgrade-mcp-integration jdatamunch 1.13.0 / jdocmunch 1.69.1 / mempalace 3.4.0 — 19 new tools routed in both CLAUDE.md files; stale `state/post-upgrade-needed` flag cleared |
| 2026-06-10 | post-upgrade-mcp-integration v1.108.50 — `get_session_stats`, `analyze_perf`, `tune_weights`, `test_summarizer` added to jcodemunch Session & tier config in both CLAUDE.md files |
| 2026-06-10 | MCP-Universe skill regression gate — `tests/test_skills.py` (576 static tests, 0 API calls); CI job 4; 6 malformed SKILL.md files fixed (missing `---`, invalid YAML); PR #36 |
| 2026-06-10 | Skill frontmatter standard — hermes-inspired YAML spec (platforms, category, tags, prerequisites, related_skills) written to `state/skill-frontmatter-standard.md`; pilot migration of pre-mortem, smart-review, session-end-checklist, prior-art-check; PR #35 |
| 2026-06-10 | jOutputMunch adoption — `## Output Token Economy` section added to both CLAUDE.md files; adversarial-review ran (2 HIGH + 6 MEDIUM fixed); SHA-pinned citation, correct null-strip predicate, success:false clause restored; PR #33 |
| 2026-06-10 | F-03 closed — bypass instruction removed from smart-review SKILL.md Step 6 and hook stderr; hook now says "Run /smart-review" |
| 2026-06-10 | F-05 closed — `gh pr *` hook split into `gh pr create *` + `gh pr merge *`; `gh pr list/view/status` no longer blocked |
| 2026-06-10 | CYNIC-R2-4 closed — flock guard + explicit exec error handling in `scripts/jcodemunch-reindex.sh` |
| 2026-06-10 | duckdb healthcheck false-positive fixed — 3s retry for uvx cold-start in `healthcheck.sh` |
| 2026-06-06 | Smart-review auto-invocation gates — PreToolUse hooks block `git push` / `gh pr create` without review clearance marker |
| 2026-06-05 | MemPalace HNSW empty-index root cause fixed — `repair --from-sqlite` leaves 0-byte `link_lists.bin` for small collections (< 50K items); fixed by post-repair force-flush step, writer-check MCP exclusion, healthcheck per-collection sync + 0-byte detection + auto-repair; upstream bug report + PR draft written |
| 2026-06-05 | design memory system — 5 MemPalace entries (pre-mortem invariants, enforcement hook attack vectors, dreaming pipeline, Telegram gateway, HNSW/FTS5+healthcheck); `post-audit-mempalace-capture` skill committed; pre-mortem step 11 + session-end-checklist Step 6b wired |
| 2026-06-05 | pre-mortem skill hardened — 3-cycle red/blue-team; 27 patches; 2 CRITICALs + 7 HIGHs closed; MEDIUM bundle, WarGames cap, fail-closed audit, cross-session memory |
| 2026-06-05 | turbovecdb security PR #2 merged — all findings fixed, 7 new tests, 46/46 passing |
| 2026-06-04 | turbovecdb security review — 1 HIGH + 1 MEDIUM + 2 LOWs found and fixed; PR #2 submitted to kostadis/turbovecdb; 7 new tests; scale test (290K drawers) pending |
| 2026-06-03 | MemPalace community knowledge share — two GitHub Discussions published: journey/war-story post (#1685) + HNSW silent corruption technical reference (#1686); covers Rust binding bug, dict pickle, FTS5 false-ok, SQLite mismatch, nightly cron destroy |
| 2026-06-03 | Dreaming CLAUDE.md injection path closed (palace path + pattern-promotion mitigated, not closed) — URL hold-filter in `dream.sh` quarantines URL-bearing playbooks to `state/dream-pending-review/`; cascade guard preserves CLAUDE.md if all playbooks held; `dream-synthesizer` SKILL.md anti-promotion rule for citation behaviors; Stop-hook citation audit still needed to structurally close pattern-promotion |
| 2026-06-03 | Dict-pickle root cause closed — verified `_persist()` is sole `pickle.dump` in chromadb; dict can't recur via any normal op; Step 2b (dead WAL commit, failed every run) removed from repair script; Step 2c comment corrected |
| 2026-06-03 | MemPalace dict-format pickle detection hardened — `healthcheck.sh` now probes pickle type (BAD:/ERR: discrimination, traceback-safe); `mempalace-repair-now.sh` Step 2c auto-migrates dict→SimpleNamespace after every repair; three code-review bugs fixed |
| 2026-06-03 | SQLite WAL data race bug fixed — upgraded to 3.51.3 via pysqlite3 source build; `.pth` patch covers all venv processes; install.sh step 2b auto-rebuilds on fresh machines; scan-commit.sh lockfile exemption fixed |
| 2026-06-03 | FTS5 corruption root cause eliminated — disabled `fts5-guard.sh` (concurrent B-tree corruptor), fixed `session-start-autofix.sh` to use venv Python + PRAGMA quick_check + flock, fixed healthcheck false-ok (was using FTS5 integrity-check), fixed `install_cron()` prefix matching, deduplicated 6 crontab entries; HEALTHCHECK: ok |
| 2026-05-28 | Review-queue triage workflow — `review-queue-triage` skill in regular session rhythm; `_review/` cleared |
| 2026-05-28 | Telegram multi-agent routing — `/work <msg>` dispatches to project-context Claude (CLAUDE.md loaded); default stays restricted; `config/telegram-agents.toml` config; hardcoded fallback on missing/malformed TOML; PR #20 |
| 2026-05-28 | MemPalace HNSW nightly destruction fixed — three-bug root cause: missing `--skip-if-healthy`, WAL never committed to HNSW, post-repair check SQLite-only; PR #19 |
| 2026-05-27 | `install-reliability.sh` plugin auto-install — superpowers + ralph-wiggum at user scope; `skill-link.sh` Stop hook no longer unlinks global-skills |
| 2026-05-27 | FTS5 guard + repair/mine coordination + skill-link blocking fix; `features/mempalace/install.sh` cron coordination; PR #14 |
| 2026-05-26 | `scripts/refinery-doctor.sh` — config drift detection + repair; 4 checks: embed-model, jcodemunch-scope, claude-md-sync, env-placeholders; atomic `--fix`; PR #13 |
| 2026-05-26 | `skill-link.sh` walks `global-skills/` — all globally promoted skills now auto-symlink on every session open; no manual `install-reliability.sh` needed after `git pull` |
| 2026-05-26 | 5 machine-local skills promoted to global — `pre-mortem`, `healthcheck-interactive-hints`, `mempalace-boot-repair-always-runs`, `platform-removal-cleanup`, `stop-hook-dedup-guard` |
| 2026-05-26 | `pre-mortem` skill restored — adversarial failure analysis (12 dimensions, WarGames escalation) synced from dma64 machine; discipline system fully operational |
| 2026-05-26 | `stack-not-at-head` resolved — jcodemunch-mcp 1.108.20 → 1.108.24; healthcheck path check relaxed to accept code-index venv |
| 2026-05-26 | `SessionStart` git fetch hook — async `git fetch --quiet` wired in `~/.claude/settings.json`; remote tracking state no longer stale at session open |
| 2026-05-26 | `uncle-j-mempalace-repair` cron restored — 4am nightly `mempalace repair` re-added to crontab; was dropped during `@reboot --skip-if-healthy` transition |
| 2026-05-25 | Blocking discipline hooks wired — `edit-surface-guard.sh` (pre-mortem gate on surface-list edits) and `grep-guard.sh` (routes `grep -r` to jcodemunch); `install-reliability.sh` now installs them on fresh machine |
| 2026-05-25 | `@reboot` repair made conditional (`--skip-if-healthy`); repair output now streams live |
| 2026-05-25 | MemPalace dict-format pickle root cause found — migrated `f89df21a` to `PersistentData`; fixed FTS5; fixed `mempalace-health.py` live query; added SessionStart health check hook |
| 2026-05-25 | `session-status-briefing` skill updated — now includes HANDOFF.md read and healthcheck.sh run as mandatory first steps |
| 2026-05-24 | MemPalace self-healing repair — FTS5 auto-rebuild pre-flight added to both `repair --yes` and `repair-hnsw rebuild` paths; 3 regression tests in repair.py, 2 in cli.py; fog-of-chess wing deleted (437K drawers); HNSW rebuilt clean at ~94K |
| 2026-05-24 | `mempalace-repair-verify.sh` — new verification script: SQLite vs HNSW count, FTS5 integrity check, semantic search smoke test |
| 2026-05-24 | `mempalace-delete-wing.py` — new utility: deletes a MemPalace wing by drawer prefix |
| 2026-05-23 | MemPalace HNSW permanent fix — `chroma-hnswlib==0.7.6` pinned in project deps; `CHROMA_API_IMPL=chromadb.api.segment.SegmentAPI` set in all mine/repair/MCP scripts and crontab; health check thresholds corrected; stop hook routes via script |
| 2026-05-23 | MemPalace HNSW corruption root-cause fix — `hnsw:num_threads=1` on all collections neutralizes updatePoint race; health check now detects trillion-element header corruption; `mempalace-repair-now.sh` added |
| 2026-05-23 | Nightly MemPalace repair cron — 4am automated `mempalace repair` prevents HNSW drift; healthcheck detects drift and prompts repair |
| 2026-05-23 | Session-end checklist system — three-layer enforcement (skill → Stop hook → pre-commit block) |
| 2026-05-23 | Standard project docs — LICENSE (AGPL-3.0), CONTRIBUTING.md, SECURITY.md, ROADMAP.md |
| 2026-05-23 | `telegram-inline-button-promote` skill — inline keyboard button wiring pattern documented |
| 2026-05-23 | `session-end-checklist` skill symlinked — invocable as `/session-end-checklist` |
| 2026-05-23 | Telegram backlog age filter — drops messages >10 min old to prevent rate-limit burn |
| 2026-05-23 | `install.sh`: Telegram overwrite protection — `[y/N]` default, skip if not configured |
| 2026-05-23 | `install.sh`: Context7 API key setup — auto-reads `context7.key`, falls back to prompt |
| 2026-05-23 | Context7 API key configured — `~/.claude/.env` populated |
| 2026-05-23 | Git pull — merged 22 upstream commits; ECC agents, healthcheck-notify, new skills |
| 2026-05-22 | Telegram gateway notifications — healthcheck alerts, skill drafts, Ralph/dream FYIs |
| 2026-05-22 | Skill approval flow — auto-maintain drafts skills instead of auto-committing |
