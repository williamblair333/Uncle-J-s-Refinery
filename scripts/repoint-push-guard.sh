#!/usr/bin/env bash
# repoint-push-guard.sh — point the deployed PreToolUse push hook at the
# versioned hooks/discipline/push-guard.sh instead of the inline upstream regex.
#
# WHY A SCRIPT AND NOT A ONE-LINER
# This edit has to be made by hand, because the agent harness can neither read
# nor write ~/.claude/settings.json. The first hand-pasted attempt was
# line-wrapped by the terminal mid-string, which wrote a command containing an
# embedded newline: `bash\n  ~/.claude/...`. That parses as TWO commands — a bare
# `bash` that swallows the hook's stdin payload, then the guard with nothing on
# stdin, which exits 0. Result: the guard silently allows everything. A disabled
# security control is worse than the false positive it was meant to fix.
# A script removes the paste entirely.
#
# Safe to re-run: idempotent, verifies before and after, and refuses rather than
# guessing whenever what it finds is not what it expects.

set -uo pipefail

SETTINGS="${1:-$HOME/.claude/settings.json}"
TARGET='bash ~/.claude/hooks/discipline/push-guard.sh'
MARKER='Direct push to main/master/production'

die()  { printf '  FAIL  %s\n' "$*" >&2; exit 1; }
ok()   { printf '  OK    %s\n' "$*"; }
note() { printf '  ..    %s\n' "$*"; }

command -v jq >/dev/null 2>&1 || die "jq not found (it is the guardrails hard prerequisite)"
[ -f "$SETTINGS" ] || die "not found: $SETTINGS"
jq -e . "$SETTINGS" >/dev/null 2>&1 || die "$SETTINGS is not valid JSON — refusing to touch it"

# The script must exist before we point anything at it, or we would swap a
# working guard for a dangling path that fails open.
GUARD="$HOME/.claude/hooks/discipline/push-guard.sh"
[ -e "$GUARD" ] || die "$GUARD missing — run install-reliability.sh first"
[ -x "$GUARD" ] || die "$GUARD not executable"

# ── Already done? ────────────────────────────────────────────────────────────
if jq -e --arg t "$TARGET" \
    '[.hooks.PreToolUse[]?.hooks[]?.command // "" | select(. == $t)] | length > 0' \
    "$SETTINGS" >/dev/null 2>&1; then
    ok "already repointed — nothing to do"
    exit 0
fi

# ── Mangled by a previous hand-edit? ─────────────────────────────────────────
# A hook that MENTIONS push-guard.sh but is not byte-equal to the target is the
# line-wrapped-paste failure: `bash\n  ~/.claude/...` parses as a bare `bash`
# (which eats the stdin payload) followed by the guard with no input, so it exits
# 0 and allows everything. Detect it explicitly — the marker search below would
# otherwise report "nothing matched", which is safe but hides a disabled guard.
MANGLED=$(jq -r --arg t "$TARGET" \
    '[.hooks.PreToolUse[]?.hooks[]?.command // ""
      | select(contains("push-guard.sh")) | select(. != $t)] | length' \
    "$SETTINGS" 2>/dev/null || echo 0)
if [ "$MANGLED" != "0" ]; then
    printf '  FAIL  %s hook(s) reference push-guard.sh but do not match it exactly.\n' "$MANGLED" >&2
    printf '        This is the line-wrapped-paste failure: the guard is DISABLED\n' >&2
    printf '        (it allows everything). Restore a known-good backup first:\n' >&2
    printf '          ls -1t %s.bak.* | head\n' "$SETTINGS" >&2
    printf '          cp <backup> %s\n' "$SETTINGS" >&2
    printf '        Then re-run this script.\n' >&2
    exit 1
fi

# ── Locate exactly one inline guard ──────────────────────────────────────────
COUNT=$(jq --arg m "$MARKER" \
    '[.hooks.PreToolUse[]?.hooks[]?.command // "" | select(contains($m))] | length' \
    "$SETTINGS" 2>/dev/null || echo 0)

case "$COUNT" in
    1) note "found 1 inline push guard" ;;
    0) die  "no inline push guard found (marker: $MARKER). Nothing matched — refusing to guess." ;;
    *) die  "found $COUNT matching hooks; expected exactly 1. Resolve by hand." ;;
esac

# ── Back up ──────────────────────────────────────────────────────────────────
BACKUP="$SETTINGS.bak.pushguard.$(date +%Y%m%d-%H%M%S)"
cp "$SETTINGS" "$BACKUP" || die "backup failed — not proceeding"
ok "backed up to $BACKUP"

# ── Apply via --arg so the value can never be re-parsed or line-wrapped ──────
TMP=$(mktemp) || die "mktemp failed"
if ! jq --arg m "$MARKER" --arg t "$TARGET" \
    '(.hooks.PreToolUse[]?.hooks[]? | select((.command // "") | contains($m)) | .command) = $t' \
    "$SETTINGS" > "$TMP" 2>/dev/null
then
    rm -f "$TMP"; die "jq transform failed — $SETTINGS unchanged"
fi

# ── Verify the OUTPUT before it replaces anything ───────────────────────────
jq -e . "$TMP" >/dev/null 2>&1 || { rm -f "$TMP"; die "result is not valid JSON — aborted"; }

# Exactly one hook must now carry the target, byte-for-byte. An embedded newline
# or stray whitespace fails this check — that is the whole point.
GOT=$(jq -r --arg t "$TARGET" \
    '[.hooks.PreToolUse[]?.hooks[]?.command // "" | select(. == $t)] | length' "$TMP")
[ "$GOT" = "1" ] || { rm -f "$TMP"; die "expected 1 exact-match hook after transform, got $GOT — aborted"; }

# The rest of the hook tree must be intact: the other guardrails entries stay.
BEFORE=$(jq '[.hooks.PreToolUse[]?.hooks[]?] | length' "$SETTINGS")
AFTER=$(jq  '[.hooks.PreToolUse[]?.hooks[]?] | length' "$TMP")
[ "$BEFORE" = "$AFTER" ] || { rm -f "$TMP"; die "hook count changed $BEFORE -> $AFTER — aborted"; }

mv "$TMP" "$SETTINGS" || { rm -f "$TMP"; die "mv failed — $SETTINGS unchanged"; }
ok "repointed ($BEFORE PreToolUse hooks preserved)"

# ── Prove it works through the deployed path ────────────────────────────────
probe() {
    printf '{"tool_input":{"command":%s}}' "$(jq -Rn --arg c "$1" '$c')" \
        | bash "$GUARD" >/dev/null 2>&1
    echo $?
}
[ "$(probe 'git push origin main')" = "2" ] \
    || die "SMOKE TEST FAILED: a direct push to main is no longer blocked. Restore: cp $BACKUP $SETTINGS"
[ "$(probe 'git push -u origin feat/x; git rev-parse main')" = "0" ] \
    || die "SMOKE TEST FAILED: the false positive is still blocked. Restore: cp $BACKUP $SETTINGS"
ok "smoke test: blocks push to main, allows feature-branch push"

printf '\n  Done. Takes effect at the NEXT session start.\n'
printf '  Restore if needed:  cp %s %s\n' "$BACKUP" "$SETTINGS"
