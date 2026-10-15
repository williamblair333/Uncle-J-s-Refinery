# Antigravity CLI (agy): headless use from scripts and other agents

Gemini CLI stopped serving personal Google accounts (AI Pro, Ultra, free) on 2026-06-18.
`agy` is the replacement and runs on the Google AI Pro subscription.

## Pieces

| File | What it does |
|---|---|
| `permissions.json` | Read-only shell allow list plus a deny list for destructive commands. |
| `apply_permissions.py` | Merges those rules into `~/.gemini/antigravity-cli/settings.json` (keeps agy's own keys, atomic, `.bak`). |
| `../../scripts/ask_agy.py` | Runs one prompt headless; exit 0 only when the turn really succeeded. |

```bash
.venv/bin/python features/antigravity/apply_permissions.py
.venv/bin/python scripts/ask_agy.py --cwd /path/to/repo "question"
.venv/bin/python scripts/ask_agy.py --cwd /tmp/work --edits "/to-questionnaire ..."
```

## Why the wrapper exists

In print mode agy exits 0 with `status: SUCCESS` even when the work did not happen:

- **Deny rule hit:** the tool step ends in `ERROR`, `denied_actions` stays empty, and the
  model often answers "DONE" anyway.
- **Command on no list:** it is soft-denied (`denied_actions` set) and the response is empty.

`ask_agy.py` reads the stream-json events and fails on either, naming the command.

## Verified behaviour (agy 1.3.5, 2026-10-15)

Re-run these after an agy update: it self-updates and rule matching is closed source.

| Probe | Result |
|---|---|
| `ls -la` (allowed) | runs |
| `ls; touch X` (touch denied) | blocked: "Matches user-configured deny rule" |
| `ls && mkdir X` (mkdir on no list) | soft-denied, nothing created |
| `ls $(touch X)`, `echo x \| xargs touch X` | denied |
| `cat /etc/hostname > ~/file` (write outside workspace) | denied, nothing written |

Each part of a compound command is checked separately, so allowing `ls` does not allow
what is chained after it.

## Skills

agy reads `~/.gemini/skills` (linked by `scripts/skill-link.sh`). `/skills` lists all of
ours, but in print mode only agy's built-ins sit in the model's context, so our skills do
not fire on their own: invoke them by name (`/teach`, `/to-questionnaire ...`).
