#!/usr/bin/env bash
# Drain the stale Telegram getUpdates backlog and reset the gateway offset.
#
# WHY: a second no-offset getUpdates consumer (lib/notify-telegram.sh, now removed)
# corrupted the shared update offset — it froze at a bogus value (HIGHER than any real
# update_id), so the backlog never confirmed and the gateway re-skipped it every 2 min
# (the message flood). Removing the second consumer (PR B) stops the RECURRENCE; this
# one-shot drain UNSTICKS the current freeze by confirming the whole backlog and writing
# a correct offset (= newest update_id + 1). Run it once after merging PR B.
#
# SAFE BY DEFAULT: dry-run (read-only). It reports the stored offset, the backlog size,
# and the NEWEST update's age, and WARNS if the newest update is fresh (<600s) — a fresh,
# unprocessed message would be skipped by a drain. Pass --confirm to actually drain.
#
# IMPORTANT — pause the gateway cron first. The `uncle-j-telegram-gateway` cron runs
# getUpdates every 2 min; if it runs while this script does, the two race for the same
# update cursor and the drain may be inconsistent. Comment that cron line out (or run
# `crontab -e`), run this with --confirm, verify, then re-enable the cron.
#
# Usage:
#   bash scripts/telegram-drain-offset.sh            # dry-run: inspect the backlog
#   bash scripts/telegram-drain-offset.sh --confirm  # drain + reset offset
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OFFSET_FILE="$PROJ_ROOT/state/telegram-gateway-offset.txt"
ENV_FILE="$PROJ_ROOT/.env"

CONFIRM=0
[[ "${1:-}" == "--confirm" ]] && CONFIRM=1

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN not set (.env missing?)" >&2
  exit 1
fi
API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

CUR_OFFSET="0"
[[ -f "$OFFSET_FILE" ]] && CUR_OFFSET="$(cat "$OFFSET_FILE")"

# Earliest unconfirmed updates (no offset → non-confirming; shows the backlog tail).
PEEK=$(curl -sf "${API}/getUpdates?limit=100&timeout=0" 2>/dev/null) \
  || { echo "ERROR: getUpdates peek failed" >&2; exit 1; }
# Newest update (offset=-1 → returns the last update, non-confirming). This is the true
# high-water mark used for the drain, independent of how deep the backlog is.
LAST=$(curl -sf "${API}/getUpdates?offset=-1&limit=1&timeout=0" 2>/dev/null) \
  || { echo "ERROR: getUpdates(offset=-1) failed" >&2; exit 1; }

# Inspect: print backlog summary + newest-update age. Exit 3 if the newest is fresh.
# `|| PEEK_RC=$?` captures the code without set -e aborting on the non-zero (3) path.
PEEK_RC=0
python3 - "$PEEK" "$LAST" "$CUR_OFFSET" <<'PYEOF' || PEEK_RC=$?
import sys, json, time
peek_raw, last_raw, cur_offset = sys.argv[1], sys.argv[2], sys.argv[3]
def updates(raw):
    try:
        d = json.loads(raw)
    except Exception as e:
        print(f"could not parse getUpdates response: {e}"); sys.exit(1)
    return d.get("result", []) if d.get("ok") else []
def age_of(u, now):
    msg = u.get("message") or u.get("callback_query", {}).get("message") or {}
    return int(now - msg.get("date", 0)) if msg.get("date") else -1
# Merge both probes (the live gateway cron may empty one of them mid-race).
merged = {u.get("update_id"): u for u in (updates(peek_raw) + updates(last_raw))
          if u.get("update_id") is not None}
now = time.time()
print(f"stored offset:        {cur_offset}")
print(f"updates visible:      {len(merged)}")
if not merged:
    print("queue is empty — nothing to drain (or the gateway cron just consumed it).")
    sys.exit(0)
ids = sorted(merged)
newest = merged[ids[-1]]
newest_age = age_of(newest, now)
print(f"oldest update_id:     {ids[0]}")
print(f"newest update_id:     {ids[-1]}  (age {newest_age}s)")
print(f"drain would set offset to: {ids[-1] + 1}")
fresh = 0 <= newest_age < 600
if fresh:
    print("WARNING: newest update is FRESH (<600s) — a drain would skip an "
          "unprocessed message. Answer it first, or proceed only if it's junk.")
sys.exit(3 if fresh else 0)
PYEOF
[[ "$PEEK_RC" -eq 1 ]] && exit 1
# PEEK_RC == 3 means the newest update is fresh; the warning already printed above.
# Fall through so the dry-run footer prints and --confirm still reports its decision.

if [[ "$CONFIRM" -eq 0 ]]; then
  echo
  echo "DRY RUN — nothing changed. Re-run with --confirm to drain and reset the offset."
  exit 0
fi

# --confirm with a fresh (<600s) newest update would skip an unprocessed message. Refuse.
if [[ "$PEEK_RC" -eq 3 ]]; then
  echo "REFUSING to drain: the newest update is fresh (<600s) and would be skipped." >&2
  echo "Answer it first (let the gateway process it), then re-run --confirm." >&2
  exit 2
fi

# --confirm: new offset = (max update_id across both probes) + 1 — the canonical full
# drain. Both probes are merged so a cron race that empties one doesn't undershoot.
NEW_OFFSET=$(python3 - "$PEEK" "$LAST" <<'PYEOF'
import sys, json
def ids(raw):
    d = json.loads(raw)
    return [u.get("update_id") for u in (d.get("result", []) if d.get("ok") else []) if u.get("update_id") is not None]
allids = ids(sys.argv[1]) + ids(sys.argv[2])
print(max(allids) + 1 if allids else "")
PYEOF
)
if [[ -z "$NEW_OFFSET" ]]; then
  echo "Queue is empty — nothing to drain. Offset left unchanged ($CUR_OFFSET)."
  exit 0
fi

# Confirm/forget the entire backlog (id < NEW_OFFSET) server-side, then persist locally.
curl -sf "${API}/getUpdates?offset=${NEW_OFFSET}&limit=1&timeout=0" > /dev/null 2>&1 \
  || { echo "ERROR: confirming drain (getUpdates offset=${NEW_OFFSET}) failed" >&2; exit 1; }
TMP="${OFFSET_FILE}.tmp"
printf '%s' "$NEW_OFFSET" > "$TMP"
mv -f "$TMP" "$OFFSET_FILE"
echo "Drained. Offset reset: ${CUR_OFFSET} -> ${NEW_OFFSET}"
echo "Next: DM the bot to confirm the gateway replies (live inbound test)."
