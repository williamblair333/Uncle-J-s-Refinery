#!/usr/bin/env bash
# vault-session-check.sh — Stop-hook assertion that a vault session was checkpointed.
#
# Asserts three things when a session ends:
#   1. The daily note for the SESSION'S date exists.
#   2. It carries at least one "## Session N" heading, and the file was modified
#      at or after the session started (i.e. this session wrote to it).
#   3. The vault's git tree is clean.
#
# Warns loudly on failure (stderr + Telegram + state log) and ALWAYS exits 0.
# A Stop hook that exits non-zero or blocks can trap session teardown.
#
# WHY THE DATE COMES FROM THE TRANSCRIPT, NOT `date`
#
# Using wall-clock `date +%F` at hook time breaks every session that crosses
# midnight: the entry was written into yesterday's note, and the hook would
# report today's (nonexistent) note as missing. Sessions here routinely run
# late. So the reference date is the timestamp of the first record in the
# session transcript. Wall-clock is only a fallback when no transcript is
# available.
#
# WHAT IT DELIBERATELY DOES NOT DO
#
# It never reads, echoes, or transmits note content or `git status` file
# contents — only counts and filenames. This vault holds a personal-context
# note kept out of model context and an archive containing a plaintext
# credential; see the local-only corpora section of SECURITY.md. A warning
# that quoted the offending lines would defeat that.
#
# REGISTRATION IS NOT INSTALLER-MANAGED
#
# The hook is registered in /opt/proj/jaredrhod/.claude/settings.json, which
# install.sh does not write and refinery-doctor --fix does not restore. On a
# machine rebuild this control is silently absent. Same class as the
# unversioned surface-write-guard.sh item in ROADMAP.
#
# Usage:
#   vault-session-check.sh              # Stop-hook mode, reads payload on stdin
#   vault-session-check.sh --vault DIR  # override vault path (testing)
#   VAULT_CHECK_SKIP=1                  # disable entirely
#
# Exit code is ALWAYS 0. Failure is reported, never enforced.

set -uo pipefail

VAULT="${VAULT_ROOT:-/opt/proj/jaredrhod/vaults/brain}"
STACK_ROOT="${STACK_ROOT:-/opt/proj/Uncle-J-s-Refinery}"
NOTES_SUBDIR="01 - Daily Notes"
QUIET=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --vault) VAULT="${2:-}"; shift 2 ;;
        --quiet) QUIET=1; shift ;;
        *) shift ;;
    esac
done

[[ -n "${VAULT_CHECK_SKIP:-}" ]] && exit 0

# Vault absent (other machines, fresh clones) — silently not applicable.
[[ -d "$VAULT" ]] || exit 0

# ── Read the Stop-hook payload ───────────────────────────────────────────────
# `cat` with no stdin blocks forever and would hang session teardown, so only
# read when stdin is actually a pipe.
INPUT=""
if [[ ! -t 0 ]]; then
    INPUT=$(cat 2>/dev/null || echo "")
fi

SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || echo "")
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || echo "")
[[ -n "$SESSION_ID" ]] || SESSION_ID="unknown"

# ── Session start: first record's timestamp in the transcript ────────────────
# Returns "<epoch> <YYYY-MM-DD>" or empty. Falls back to the transcript file's
# own mtime, then to wall-clock.
_session_start() {
    local t="$1"
    [[ -n "$t" && -f "$t" ]] || return 1
    python3 - "$t" <<'PY' 2>/dev/null
import json, sys, os, datetime
path = sys.argv[1]
stamp = None
try:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = rec.get("timestamp")
            if ts:
                stamp = ts
                break
except OSError:
    pass
if stamp:
    try:
        dt = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        dt = dt.astimezone()
        print("%d %s" % (dt.timestamp(), dt.strftime("%Y-%m-%d")))
        sys.exit(0)
    except ValueError:
        pass
try:
    m = os.path.getmtime(path)
    dt = datetime.datetime.fromtimestamp(m)
    print("%d %s" % (m, dt.strftime("%Y-%m-%d")))
except OSError:
    sys.exit(1)
PY
}

START_INFO="$(_session_start "$TRANSCRIPT" || true)"
if [[ -n "$START_INFO" ]]; then
    START_EPOCH="${START_INFO%% *}"
    SESSION_DATE="${START_INFO##* }"
    DATE_SOURCE="transcript"
else
    START_EPOCH=0
    SESSION_DATE="$(date +%F)"
    DATE_SOURCE="wall-clock"
fi

# ── Assertion 1: the daily note exists ───────────────────────────────────────
# Notes live in month subfolders ("08 - August 2026/2026-08-15.md"), so search
# the tree rather than assuming a layout.
NOTE=""
if [[ -d "$VAULT/$NOTES_SUBDIR" ]]; then
    NOTE="$(find "$VAULT/$NOTES_SUBDIR" -type f -name "${SESSION_DATE}.md" -print -quit 2>/dev/null || true)"
fi

FAILURES=()
DETAILS=()

if [[ -z "$NOTE" ]]; then
    FAILURES+=("no-daily-note")
    DETAILS+=("No daily note for ${SESSION_DATE} under '${NOTES_SUBDIR}/'.")
else
    # ── Assertion 2: a Session heading, written during THIS session ──────────
    SESSION_HEADINGS=$(grep -c '^## Session [0-9]' "$NOTE" 2>/dev/null || echo 0)
    SESSION_HEADINGS=${SESSION_HEADINGS//[^0-9]/}
    : "${SESSION_HEADINGS:=0}"

    if [[ "$SESSION_HEADINGS" -eq 0 ]]; then
        FAILURES+=("no-session-entry")
        DETAILS+=("$(basename "$NOTE") exists but carries no '## Session N' heading.")
    else
        NOTE_MTIME=$(python3 -c 'import os,sys; print(int(os.path.getmtime(sys.argv[1])))' "$NOTE" 2>/dev/null || echo 0)
        if [[ "$START_EPOCH" -gt 0 && "$NOTE_MTIME" -lt "$START_EPOCH" ]]; then
            FAILURES+=("stale-session-entry")
            DETAILS+=("$(basename "$NOTE") has ${SESSION_HEADINGS} session heading(s) but was last modified before this session started — nothing was appended for this session.")
        fi
    fi
fi

# ── Assertion 3: the vault tree is clean ─────────────────────────────────────
# Reduced to a count immediately; filenames and contents never leave this scope.
if git -C "$VAULT" rev-parse --git-dir >/dev/null 2>&1; then
    DIRTY=$(git -C "$VAULT" status --porcelain 2>/dev/null | grep -c . || echo 0)
    DIRTY=${DIRTY//[^0-9]/}
    : "${DIRTY:=0}"
    if [[ "$DIRTY" -gt 0 ]]; then
        FAILURES+=("vault-dirty")
        DETAILS+=("Vault git tree has ${DIRTY} uncommitted change(s) — they are not checkpointed. (A concurrent session may still be working.)")
    fi
else
    FAILURES+=("vault-not-a-repo")
    DETAILS+=("${VAULT} is not a git repository — nothing is under version control.")
fi

# ── Record every run, pass or fail ───────────────────────────────────────────
# A checker whose own outcome goes unrecorded is indistinguishable from one
# that passed. One short line; no note content, no filenames from git.
LOG="$STACK_ROOT/state/vault-check.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
if [[ ${#FAILURES[@]} -eq 0 ]]; then
    printf '%s PASS vault-session-check date=%s src=%s session=%s\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" "$SESSION_DATE" "$DATE_SOURCE" "$SESSION_ID" >> "$LOG" 2>/dev/null || true
    exit 0
fi

JOINED=$(IFS=,; echo "${FAILURES[*]}")
printf '%s WARN vault-session-check date=%s src=%s failures=%s session=%s\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$SESSION_DATE" "$DATE_SOURCE" "$JOINED" "$SESSION_ID" >> "$LOG" 2>/dev/null || true

# ── Warn loudly ──────────────────────────────────────────────────────────────
if [[ "$QUIET" -eq 0 ]]; then
    {
        echo ""
        echo "╔══════════════════════════════════════════════════════════════╗"
        echo "║  ⚠  VAULT SESSION NOT CHECKPOINTED                           ║"
        echo "╚══════════════════════════════════════════════════════════════╝"
        echo ""
        for d in "${DETAILS[@]}"; do
            echo "  • $d"
        done
        echo ""
        echo "  Vault: $VAULT"
        echo "  Fix:   append '## Session N' to the ${SESSION_DATE} daily note,"
        echo "         then commit the vault. See CLAUDE.md — checkpoint persistence."
        echo ""
    } >&2
fi

# Telegram — same credential source and failure posture as session-end-check.sh.
ENV_FILE="$STACK_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a && source "$ENV_FILE" 2>/dev/null && set +a || true
fi

if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    MSG="⚠️ Vault not checkpointed (${SESSION_DATE}): ${JOINED}. Append the session entry and commit the vault."
    DEDUP_FILE="$STACK_ROOT/state/vault-check-dedup.txt"
    MSG_HASH="$(printf '%s' "$MSG" | md5sum | cut -c1-16)"
    NOW="$(date +%s)"
    _skip=0
    if [[ -f "$DEDUP_FILE" ]]; then
        _prev_hash="$(cut -f1 "$DEDUP_FILE" 2>/dev/null)"
        _prev_ts="$(cut -f2 "$DEDUP_FILE" 2>/dev/null)"
        [[ "$_prev_hash" == "$MSG_HASH" && $(( NOW - ${_prev_ts:-0} )) -lt 15 ]] && _skip=1
    fi
    if [[ "$_skip" -eq 0 ]]; then
        printf '%s\t%s\n' "$MSG_HASH" "$NOW" > "$DEDUP_FILE" 2>/dev/null || true
        curl -sf -X POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -H "Content-Type: application/json" \
            -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"$MSG\"}" \
            >/dev/null 2>&1 || true
    fi
fi

exit 0
