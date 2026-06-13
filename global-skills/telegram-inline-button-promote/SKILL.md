---
name: telegram-inline-button-promote
description: Wire up a Telegram inline keyboard button in a polling bot — add button to outbound notification, subscribe to callback_query updates, answer the callback, and collapse a multi-step confirm flow into a single button press.
---

## When to use

Use this skill when you want to replace a multi-step Telegram text command (e.g. `promote <id>` → `promote <id> global`) with a single inline button press baked into the outbound notification itself.

Applies to projects that:
- Send Telegram notifications via a shell/Python notify lib
- Run a polling bot that reads `getUpdates` in a loop
- Currently use a two-step confirm flow for a privileged action

## Prerequisites

- The notify lib must expose a function that accepts a `reply_markup` / inline keyboard argument (e.g. `notify_send_pitch` vs the simpler `notify_send_text`).
- The polling bot must be editable Python or shell.

## Key steps

### 1. Check memory and notify lib first
.venv-memweave/bin/python scripts/memweave/mw_search.py "<feature area> promote flow" --k 5
# Then read lib/notify.sh (or equivalent) to find the pitch/button function

### 2. Add the inline button to the outbound notification

Replace the plain-text send call with the one that accepts `reply_markup`:
# Before
notify_send_text(chat_id, text)

# After — inline_keyboard is a list-of-rows, each row a list of buttons
reply_markup = {
    "inline_keyboard": [[
        {"text": "✅ Promote Global", "callback_data": f"promote_global:{item_id}"}
    ]]
}
notify_send_pitch(chat_id, text, reply_markup=reply_markup)

### 3. Subscribe the polling bot to callback_query updates

In `getUpdates`, add `callback_query` to `allowed_updates`:
params = {
    "offset": offset,
    "timeout": 30,
    "allowed_updates": ["message", "callback_query"],   # <-- add this
}

### 4. Add answer_callback_query helper (above the loop)

Place this before the update loop so it's in scope:
def answer_callback(callback_id, text=""):
    requests.post(f"{API}/answerCallbackQuery", json={
        "callback_query_id": callback_id,
        "text": text,
    })

Always call this to dismiss the loading spinner on the button.

### 5. Handle callback_query at the top of the update loop

for update in updates:
    # Callback queries come in before messages — handle first
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")
        answer_callback(cq["id"])

        if data.startswith("promote_global:"):
            item_id = data.split(":", 1)[1]
            do_promote_global(item_id)          # direct action, no confirm step
        continue

    msg = update.get("message", {})
    # ... rest of message handler

### 6. Remove the old multi-step text-command confirm block

Delete (or simplify) the code that was waiting for a second `promote <id> global` message. The inline button encodes the full intent in `callback_data`, so no confirm round-trip is needed.

### 7. Move shared helpers above the loop

Any helper functions referenced by both the callback handler and the message handler (e.g. `find_draft`, `install_skill`) must be defined above the update loop, not inside a branch of it.

## Sanity checks after editing

python3 -c "import ast, sys; ast.parse(open('scripts/your-bot.py').read()); print('OK')"
# Verify no stale references to removed variables
grep -n "old_var_name" scripts/your-bot.py

## Common pitfalls

- Forgetting to call `answer_callback_query` — the button stays in "loading" state forever.
- Defining helpers inside the loop — they shadow or error on the second iteration.
- Not adding `callback_query` to `allowed_updates` — Telegram silently drops them.
- Reusing a variable name from the old two-step flow in the new single-step handler.
