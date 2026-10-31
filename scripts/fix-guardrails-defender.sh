#!/usr/bin/env bash
# Replace the upstream claude-guardrails prompt-injection-defender with the repo's repaired copy.
#
# Upstream reads `.tool_output` and prints `{"message": …}`, so it has never warned (see the
# header of hooks/guardrails/prompt-injection-defender.sh). install-guardrails.sh re-copies the
# upstream file on every run, so it calls this afterwards; run it by hand after a pull on any
# other host. The installed file is replaced only when it is the known upstream version (or a
# previous repo copy); anything else is left alone with a warning, so a real upstream change
# gets a human look instead of a silent overwrite. Atomic write + .bak backup. Idempotent.
#
# Usage: fix-guardrails-defender.sh [--check]     (--check: report only; exit 1 if not repaired)
set -euo pipefail
STACK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$STACK_ROOT/hooks/guardrails/prompt-injection-defender.sh"
DEST="${HOME}/.claude/hooks/prompt-injection-defender/prompt-injection-defender.sh"
MODE="${1:-fix}"
# sha256 of every upstream version this repair knows to be broken.
KNOWN_UPSTREAM=(40762f36e0a998178f38c5fcb6945731e08972273ae562faf48ccee7f4a7cd2e)

[[ -f "$DEST" ]] || { echo "    OK  no guardrails defender installed — nothing to repair"; exit 0; }

have=$(sha256sum "$DEST" | cut -d' ' -f1)
want=$(sha256sum "$SRC" | cut -d' ' -f1)
if [[ "$have" == "$want" ]]; then
  echo "    OK  guardrails defender is the repaired copy"
  exit 0
fi

known=0
for k in "${KNOWN_UPSTREAM[@]}"; do [[ "$have" == "$k" ]] && known=1; done
# A previous repaired copy carries this marker; replacing it with the current one is safe.
grep -q 'Repo-owned repair of dwarvesf/claude-guardrails' "$DEST" && known=1

if [[ "$MODE" == "--check" ]]; then
  if (( known )); then
    echo "    X   guardrails defender is the broken upstream copy (never warns) — run scripts/fix-guardrails-defender.sh"
  else
    echo "    !   guardrails defender is an unknown version ($have) — review it against $SRC"
  fi
  exit 1
fi

if (( ! known )); then
  echo "    !   guardrails defender is an unknown version ($have); left alone." >&2
  echo "        If upstream fixed it, compare with $SRC; else add its sha256 to KNOWN_UPSTREAM." >&2
  exit 1
fi

cp -p "$DEST" "$DEST.bak"
tmp=$(mktemp "$(dirname "$DEST")/.pid.XXXXXX")
cp "$SRC" "$tmp"
chmod 755 "$tmp"
mv -f "$tmp" "$DEST"
echo "    OK  installed the repaired guardrails defender at $DEST (upstream copy kept as .bak)"
