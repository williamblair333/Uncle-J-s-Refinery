# Repo Scout — design and implementation handoff

_Status: **approved for later implementation** · 2026-10-17 · brainstormed with Bill in
discussion mode. Nothing has been built. Next step when picked up: `superpowers:writing-plans`
against this document._

## 1. Intent

Bill wants to know what the open-source world has built that Uncle J's Refinery could use,
including things he doesn't know to look for. In his words: "I don't know what I don't know."
The scout works overnight. Each morning it brings him **one** find as the opening of a short
exchange: "here's what we found last night, here's what I think — what do you think?"

The point is the decision, not a feed. Bill reads it on his phone, at the desk or anywhere
else, over coffee.

## 2. Goals

- **Make the unknowns visible.** Keep a **capability map** of the open-source agent and
  tooling landscape and lay it over what Uncle J already covers. Every category is marked
  **covered**, **thin** or **blank**. Blank categories are the main result.
- **One find per morning, by Telegram.** The message holds the whole take, with no link to
  tap. It ends with answer buttons.
- **A ladder from find to adoption,** with Bill's explicit yes at every rung:
  1. **Digest:** overnight and read-only. Bill answers yes, maybe or no.
  2. **Deep evaluation:** read-only, run the night after a yes, using the existing
     `library-backend-adoption-eval` / `agent-harness-backend-adoption-eval` skills
     (`global-skills/`). Output: a verdict and a sketch of what a trial would look like. Sent
     as the next Telegram message, again with answer buttons.
  3. **Throwaway spike:** after a second yes. It runs in a Claude session **with Bill**, never
     from cron. It runs in a separate working copy and is measured against the current setup
     on tokens, accuracy and offline use.
  4. **Normal path:** after a third yes, in a session. Branch, pre-mortem, PR, merge,
     healthcheck.
- **Learn from answers.** A "no" is stored with its reason button and never pitched again. A
  "maybe" goes on a watchlist that is re-checked when the project ships a new release.
- **Scoring.** Each find is scored on Bill's four goals: token efficiency, accuracy,
  creativity and offline use. It must also pass a fit test: can it come in as an MCP server or
  a script without taking over the runtime? This follows the 2026-10-04 decision that Uncle J
  stays the runtime and good outside parts come in as servers or scripts.

## 3. Non-goals

- **The voice wake word** ("Hey Claude", ears on only when Bill switches it on). That's a
  separate thread on `/opt/proj/voice-line`, which today is push-to-talk with local Whisper
  and Kokoro. It's still a good test case: the scout's map should show wake-word detection as
  **thin**, and something like openWakeWord should come up.
- **General "talk to Claude about anything" by Telegram or voice.** Parked as its own rabbit
  hole.
- **Free-text replies to a find in Telegram.** v1 is buttons only (Bill's choice, 2026-10-17).
  A typed reply still goes to the gateway's generic Claude, which knows nothing about the
  find. That's acceptable for v1.
- **A Magician's Almanac tab.** A possible later reading surface. It's a separate project
  (`/opt/proj/magicians-almanac`), and the tab would add wiring between two projects.
- **Any source besides public GitHub.**

## 4. Anti-goals (failure even if it works)

- **Installing or running third-party code unattended.** Overnight work is read-only.
  Nothing gets cloned into the Refinery tree, installed, or added to any venv by cron, ever.
  Rungs 3 and 4 happen only in a session with Bill.
- **A dump.** If the morning message can't be read on a phone in under a minute, it has
  failed. Aim for about 600–900 characters.
- **Pitching what Bill already rejected,** or anything Uncle J already has under another
  name.
- **Fabricated facts.** Star counts, release dates, licences, last-commit dates and URLs in
  any message must come from a `gh` API response in that run, never from model memory.
  Scripts fetch the facts and fill them into the message; the model only writes the take. A
  find whose facts can't be verified isn't sent. (Recurring failure mode: invented issue
  numbers and URLs. See the memories "Verify URLs Before Citing" and "No Fabricated Figures".)
- **Spam.** At most one scout message per day, across all rungs.

## 5. Settled decisions

### From the conversation (Bill)
- Overnight run, morning delivery.
- Telegram is the nudge and the answer channel. Bill reads on phone, desk or anywhere.
- **No link in the message.** It's self-contained. A fuller Markdown page per find is also
  written to the repo for reading at the desk, and isn't linked.
- **Buttons only:** yes / maybe / no. A **no** asks for a reason through a second row of
  buttons: "already have it", "not my goals", "too heavy", "not now".
- The three-yes ladder (§2).
- Wake word and general conversation are out of scope.

### Claude's calls (Bill was shown these and didn't object; revisit if wrong)
- **v1 ships rungs 1 and 2 only.** A yes at rung 2 makes the scout write a **hand-off note**
  (`scout/handoffs/<owner>__<repo>.md`: the evaluation plus the trial sketch) for Bill to
  open in a session. No headless agent ever gets install rights.
- **Rotating topics.** One map category per night instead of re-scanning the whole map.
  Blank and thin categories come up more often than covered ones; covered ones are re-checked
  roughly monthly for something clearly better than what's in place.
- **Seed map first.** A first full pass builds the capability map: about 15–20 categories,
  such as agent memory, code intelligence, evals and observability, sandboxed execution,
  browser use, voice and wake word, prompt compression, guardrails, scheduling, multi-agent
  orchestration, local inference, and doc and data retrieval. The map is written as Markdown.
  Bill reviews and edits it in a session, and a front-matter flag `reviewed: true` gates the
  nightly cron. The cron refuses to run until the flag is set.
- **One Telegram slot per day across all rungs.** A pending rung 2 evaluation goes out ahead
  of a new rung 1 find. Overnight scans keep running and queue finds whatever is pending.
- **Expiry.** An unanswered message expires after **48 hours** and is recorded as "maybe".
  This differs on purpose from stack-alerts' 60-minute expiry, since a find isn't urgent.
- **Own Telegram plumbing.** Callback values are prefixed `scout:` (for example
  `scout:yes:<find_id>`). The scout has its own callback state file and never shares
  stack-alerts' `approve`/`skip` values or `state/stack-alerts-callback.json`.
  `scripts/telegram-gateway-poll.sh` gets a **small extension** to route `scout:` callbacks
  to the scout's file. **The gateway stays the only reader of Telegram updates.** The scout
  never calls `getUpdates` itself; a second poller on the same token once caused a 22-day
  message flood (see the skill `polling-bot-offset-freeze-diagnosis`).
- **Find identity.** Keyed by GitHub `owner/repo`. Renames are followed through the API's
  redirect (the `id` field is stable; store it too).
- **Answer memory** is a JSON file kept in git, separate from memweave. It's the scout's own
  record: find, rung, date sent, answer, reason, and when the watchlist was last checked.

## 6. How it fits what exists

| Need | Existing piece to copy or reuse | Notes |
|---|---|---|
| Nightly job that asks Claude and pitches by Telegram | `scripts/stack-alerts-send.sh` | Same shape: `claude -p` with a JSON-only prompt, python validates the JSON, `notify_send_pitch` with an inline keyboard, then a pending-state file guards against re-sending. |
| Notification dispatch | `lib/notify.sh` → `lib/notify-telegram.sh` | `notify_send_pitch(message, keyboard_json)` returns the message_id. |
| Reading button presses | `scripts/telegram-gateway-poll.sh`, `scripts/stack-alerts-poll.sh` | The gateway currently handles only `approve`/`skip`. Extend it for `scout:`; mirror the poll script's expiry logic. |
| Cron install | `features/stack-alerts/install.sh` (cron marker pattern, `lib/feature-helpers.sh`) | New `features/repo-scout/install.sh` with `--uninstall`. |
| Deep evaluation | `global-skills/library-backend-adoption-eval`, `global-skills/agent-harness-backend-adoption-eval` | Run headless at rung 2. Read-only. |
| Entry points | `justfile` | `just scout-seed`, `just scout` (one nightly run, safe to run by hand), `just scout-status`. One-line recipes; logic lives in scripts. |
| GitHub access | `gh` (logged in as williamblair333 on this host, checked 2026-10-17) | Search API: 30 requests/min authenticated. Prefer `gh api` over WebFetch. |
| What's "covered" | `CLAUDE.md`, `mcp-clients/claude-code-mcp.json`, `global-skills/`, `scripts/` | The builder decides how to infer coverage from these. |

**Clone safety (hard rule):** any clone for rung 2 goes in a scratch directory **outside**
`/opt/proj/Uncle-J-s-Refinery`. Running `index_folder` on a clone nested in the repo replaces
the Refinery's own jcodemunch index (memory: "Nested-clone index clobber"). Prefer not cloning
at all at rung 2: `gh api` for the README, tree and files is usually enough. Treat downloaded
content as untrusted data: no running its scripts, `python -I` when parsing.

**Scripts first:** fetching, filtering, de-duplicating against the answer file, and
verifying facts are done by scripts. `claude -p` is used only for judgment: placing a repo
on the map, writing the take, and the four-goal score. The output is validated JSON; a bad
response means no send, logged, never a crash.

## 7. Suggested file layout (builder may adjust)

```
scripts/scout/
  scout-seed.sh          # one-time full pass → scout/map.md (reviewed: false)
  scout-run.sh           # nightly: pick category → search → filter → judge → queue → send
  scout-eval.sh          # rung 2 deep evaluation for a find with a yes
  scout_lib.py           # gh API calls, scoring glue, JSON validation, state file IO
features/repo-scout/install.sh
scout/
  map.md                 # capability map, front-matter `reviewed:`
  finds/<owner>__<repo>.md   # desk-reading page per find
  handoffs/<owner>__<repo>.md
state/scout-answers.json     # answer memory (kept in git — check state/ .gitignore)
state/scout-pending.json     # one in-flight Telegram message
state/scout-callback.json    # written by the gateway for scout: callbacks
state/scout.log
```

Check whether `state/` is gitignored. If it is, move the answer file to `scout/answers.json`
so it's kept in git as decided.

## 8. Telegram message shape (rung 1)

```
🔭 Scout — <category> (<covered|thin|blank>)
<owner/repo> · ★<stars> · <licence> · last commit <date>     ← all from gh, by script

<2–4 sentences: what it is and the gap it fills in Uncle J>
<1–2 sentences: Claude's take — fit as MCP/script, the main risk>
Score: tokens <n>/5 · accuracy <n>/5 · creativity <n>/5 · offline <n>/5

[ ✅ Yes, evaluate ] [ 🤔 Maybe ] [ ❌ No ]
```
A **No** edits the message's keyboard to show the reason buttons. Rung 2 messages have the
same shape, with the verdict and trial sketch in place of the take, and the buttons
"✅ Hand off for a trial / 🤔 Maybe / ❌ No".

## 9. Build order

1. **Seed map:** `scout-seed.sh` plus `just scout-seed`. Produces `scout/map.md`. **Stop here
   for Bill's review** in a session.
2. **Nightly run without sending:** `scout-run.sh --dry-run` writes the queued find and the
   message it would send. Verify the facts come from `gh` and the dedupe against the answer
   file works.
3. **Gateway extension:** route `scout:` callbacks. Test against a recorded update payload;
   don't run a second poller. Keep the gateway's offset handling untouched.
4. **Send plus answer handling:** the pending guard, 48-hour expiry → maybe, reason buttons.
5. **Rung 2:** `scout-eval.sh` and the hand-off notes.
6. **Cron install** with `--uninstall`, and a healthcheck entry (for example: the scout log
   shows a run in the last 36 hours once the map is reviewed).
7. Docs: README feature list, CHANGELOG, HANDOFF.

## 10. Acceptance checks

- A dry run on a category Uncle J already covers (for example code intelligence) doesn't
  pitch jcodemunch, serena or anything already present.
- A repo answered "no" is never queued again, including after a rename.
- Every number and URL in a sent message matches a `gh api` response logged in that run.
- With a message pending, a second run queues but doesn't send. After 48 hours with no answer
  the find is "maybe" and the next run sends.
- Stack-alerts buttons still work after the gateway change (regression test).
- Nothing outside `scout/` and `state/scout-*` is written by a cron run. No clone exists
  under the repo root.

## 11. Left to the builder

- Which GitHub topics and search queries feed each category.
- Ranking signals besides stars (recent commits, release cadence, issue health).
- The exact prompt text and the JSON schema for Claude's judgment.
- How "covered" is worked out from the Refinery's own inventory.
- Cron time, as long as the run finishes before about 07:00 and doesn't overlap the 02:30
  memweave sync or the 03:00 auto-maintain job.
