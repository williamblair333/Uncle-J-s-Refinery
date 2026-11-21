#!/usr/bin/env bash
# Repair upstream claude-guardrails scan-commit.sh so pinned image digests can be committed.
#
# Upstream scans staged lines with a hex-64 "generic secret" pattern. Every
# `image@sha256:<64 hex>` pin matches it, so agents can't commit a pinned compose file
# (autark's Pi-hole and ntfy were both blocked, 2026-11-21). Pinning by digest is what we
# want, so this inserts one line after ADDED is built: hex that directly follows
# "sha256:" is masked before the patterns run. Every other pattern still sees the text.
# install-guardrails.sh re-copies upstream, so it calls this afterwards. Idempotent;
# atomic write + .bak backup.
#
# Usage: fix-guardrails-digest.sh [--check] [path-to-scan-commit.sh]
set -euo pipefail
MODE="fix"
if [[ "${1:-}" == "--check" ]]; then MODE="check"; shift; fi
HOOK="${1:-${HOME}/.claude/hooks/scan-commit/scan-commit.sh}"
MARK="# refinery: fix-guardrails-digest"

if [[ ! -f "$HOOK" ]]; then
  echo "    OK  no scan-commit.sh at $HOOK — nothing to repair"
  exit 0
fi
if grep -qF "$MARK" "$HOOK"; then
  echo "    OK  scan-commit digest carve-out present"
  exit 0
fi
# The anchor: the guard that runs right after ADDED is built.
if ! grep -qE '^if \[\[ -z "\$ADDED" \]\]; then$' "$HOOK"; then
  echo "    X   scan-commit.sh changed upstream; anchor not found — patch $HOOK by hand" >&2
  exit 1
fi
if [[ "$MODE" == "check" ]]; then
  echo "    X   scan-commit blocks pinned image digests — run scripts/fix-guardrails-digest.sh"
  exit 1
fi

tmp="$(mktemp "$(dirname "$HOOK")/.scan-commit.XXXXXX")"
awk -v mark="$MARK" '
  !done && /^if \[\[ -z "\$ADDED" \]\]; then$/ {
    print mark ": a 64-hex after \"sha256:\" is a content digest, not a secret."
    print "ADDED=\"$(printf %s \"$ADDED\" | sed -E '\''s/sha256:[0-9a-fA-F]{64}/sha256:<digest>/g'\'')\""
    print ""
    done=1
  }
  { print }
' "$HOOK" > "$tmp"
chmod --reference="$HOOK" "$tmp"
cp -p "$HOOK" "$HOOK.bak"
mv "$tmp" "$HOOK"
echo "    OK  scan-commit now lets pinned image digests through ($HOOK)"
