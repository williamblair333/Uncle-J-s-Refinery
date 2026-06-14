#!/usr/bin/env bash
# Inspect / unstick the Telegram gateway getUpdates offset.
#
# WHY: a second no-offset getUpdates consumer (lib/notify-telegram.sh, removed in the
# single-consumer fix) corrupted the shared offset — it froze at a bogus value HIGHER
# than any real update_id, so the backlog never confirmed and the gateway re-skipped it
# every 2 min (the message flood). This helper unsticks the freeze.
#
# Telegram offset semantics (https://core.telegram.org/bots/api, getUpdates):
#   - getUpdates with NO offset      → returns earliest-100 unconfirmed, CONFIRMS NOTHING (read-only).
#   - getUpdates with a POSITIVE off → returns updates >= off, CONFIRMS (forgets) all < off.
#   - getUpdates with a NEGATIVE off → confirms/forgets earlier updates. NOT used here: it is a
#     footgun (it silently consumed a live test message in an earlier version of this script).
#
# Modes:
#   (default)    dry-run — read-only inspection (no-offset peek only). Changes nothing.
#   --catch-up   set the offset to the OLDEST unconfirmed id so the gateway processes the queue
#                FORWARD without skipping (use this when the offset is frozen and you want every
#                queued message answered). Writes only the local offset file; no server confirm.
#   --confirm    DRAIN — discard the stale backlog by confirming it (positive-offset loop). Refuses
#                if any fresh (<600s) update is in view, so an unanswered recent message isn't lost.
#
# Pause the `uncle-j-telegram-gateway` cron before --catch-up/--confirm so it doesn't race this
# script for the offset, then re-enable it after.
#
# Usage:
#   bash scripts/telegram-drain-offset.sh            # inspect
#   bash scripts/telegram-drain-offset.sh --catch-up # unstick, keep + process all messages
#   bash scripts/telegram-drain-offset.sh --confirm  # unstick, discard stale backlog
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OFFSET_FILE="$PROJ_ROOT/state/telegram-gateway-offset.txt"
ENV_FILE="$PROJ_ROOT/.env"

MODE="dryrun"
case "${1:-}" in
  "")          MODE="dryrun"  ;;
  --catch-up)  MODE="catchup" ;;
  --confirm)   MODE="confirm" ;;
  *) echo "usage: $0 [--catch-up|--confirm]" >&2; exit 2 ;;
esac

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN not set (.env missing?)" >&2
  exit 1
fi
API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

CUR_OFFSET="0"
[[ -f "$OFFSET_FILE" ]] && CUR_OFFSET="$(cat "$OFFSET_FILE")"

# Read-only peek: earliest-100 unconfirmed, confirms nothing.
peek() { curl -sf "${API}/getUpdates?limit=100&timeout=0" 2>/dev/null || echo '{"ok":false,"result":[]}'; }

# Analyze a peek JSON → "MIN MAX COUNT FRESH NEWEST_AGE" (or "- - 0 0 -" when empty).
analyze() {
  python3 - "$1" <<'PYEOF'
import sys, json, time
try:
    d = json.loads(sys.argv[1])
except Exception:
    d = {}
u = d.get("result", []) if d.get("ok") else []
now = time.time()
def age(x):
    m = x.get("message") or x.get("callback_query", {}).get("message") or {}
    return int(now - m.get("date", 0)) if m.get("date") else -1
ids = [x.get("update_id") for x in u if x.get("update_id") is not None]
if not ids:
    print("- - 0 0 -"); sys.exit(0)
fresh = sum(1 for x in u if 0 <= age(x) < 600)
newest = max(u, key=lambda x: x.get("update_id", 0))
print(f"{min(ids)} {max(ids)} {len(ids)} {fresh} {age(newest)}")
PYEOF
}

write_offset() {  # $1 = new offset
  local tmp="${OFFSET_FILE}.tmp"
  printf '%s' "$1" > "$tmp"
  mv -f "$tmp" "$OFFSET_FILE"
}

P="$(peek)"
read -r MIN MAX COUNT FRESH NEWAGE <<< "$(analyze "$P")"
echo "stored offset:          $CUR_OFFSET"
echo "visible (earliest 100): $COUNT update(s)"
[[ "$COUNT" != 0 ]] && echo "  id range $MIN..$MAX | newest age ${NEWAGE}s | fresh(<600s) $FRESH"

# ── dry-run ────────────────────────────────────────────────────────────────────
if [[ "$MODE" == dryrun ]]; then
  [[ "$FRESH" != 0 ]] && echo "NOTE: $FRESH fresh (<600s) update(s) present — --confirm will refuse; use --catch-up to keep them."
  echo
  if [[ "$COUNT" == 0 ]]; then
    echo "DRY RUN — queue empty, nothing to unstick. (Offset $CUR_OFFSET; if it's a bogus high"
    echo "value and a message is stuck below it, --catch-up will repoint once one is visible.)"
  else
    echo "DRY RUN — nothing changed. Options:"
    echo "  --catch-up : set offset to oldest unconfirmed (${MIN}) → gateway processes forward, no skip"
    echo "  --confirm  : drain stale backlog (refuses if any fresh update is present)"
  fi
  exit 0
fi

if [[ "$COUNT" == 0 ]]; then
  echo "Queue empty — nothing to do. Offset unchanged ($CUR_OFFSET)."
  exit 0
fi

# ── --catch-up ───────────────────────────────────────────────────────────────────
if [[ "$MODE" == catchup ]]; then
  write_offset "$MIN"
  echo "Catch-up: offset ${CUR_OFFSET} -> ${MIN}. The gateway will process the queue forward (it"
  echo "age-skips >600s messages but still advances). Re-enable the gateway cron and watch the log."
  exit 0
fi

# ── --confirm (drain stale via positive-offset confirm loop) ──────────────────────
if [[ "$FRESH" != 0 ]]; then
  echo "REFUSING to drain: $FRESH fresh (<600s) update(s) present and would be skipped." >&2
  echo "Use --catch-up to keep and process them instead." >&2
  exit 2
fi

off="$CUR_OFFSET"
drained=0
iter=0
while (( iter < 20 )); do
  read -r MIN MAX COUNT FRESH NEWAGE <<< "$(analyze "$(peek)")"
  if [[ "$COUNT" == 0 ]]; then break; fi
  if [[ "$FRESH" != 0 ]]; then
    # A fresh batch appeared mid-drain: don't confirm it. Point the offset AT it so the
    # gateway picks it up (drain stale + catch-up the fresh boundary).
    off="$MIN"
    echo "Reached fresh update(s) at id ${MIN} after draining ${drained} stale — left for the gateway."
    write_offset "$off"
    echo "Offset ${CUR_OFFSET} -> ${off}. Re-enable the gateway cron; it will answer from ${MIN}."
    exit 0
  fi
  newoff=$(( MAX + 1 ))
  curl -sf "${API}/getUpdates?offset=${newoff}&limit=1&timeout=0" > /dev/null 2>&1 \
    || { echo "ERROR: confirm (getUpdates offset=${newoff}) failed" >&2; exit 1; }
  off="$newoff"
  drained=$(( drained + COUNT ))
  iter=$(( iter + 1 ))
done

write_offset "$off"
if (( iter >= 20 )); then
  echo "Drained ${drained} (hit the 20-batch cap) — offset ${CUR_OFFSET} -> ${off}. Re-run to continue if more remain."
else
  echo "Drained ${drained}. Offset ${CUR_OFFSET} -> ${off}."
fi
echo "Next: re-enable the gateway cron and DM the bot to confirm a reply."
