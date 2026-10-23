#!/usr/bin/env bash
# precommit-scan.sh — git pre-commit gate: block a commit whose STAGED text files
# carry invisible Unicode. Report-only: it never rewrites anything.
#
# Scans the staged blobs (what will be committed), not the working tree, by
# copying each one out of the index into a temp dir. Same file selection as
# audit-repo.sh (pathspec.sh).
#
# Deliberately NOT wired: `jscrub clean`, `--in-place`, `--follow-symlinks`. A hook
# that rewrites files mid-commit would commit bytes nobody reviewed. On a hit it
# prints the findings and the manual fix, and exits 1.
#
# Exit: 0 clean or nothing to scan, 1 findings or unscannable file (blocks the
# commit). Bypass for a known-intentional fixture: add it to pathspec.sh.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JSCRUB="$SELF_DIR/jscrub"
# shellcheck source=pathspec.sh
source "$SELF_DIR/pathspec.sh"

cd "$REPO_ROOT"
mapfile -d '' STAGED < <(git diff --cached --name-only --diff-filter=ACMR -z -- "${JSCRUB_PATHSPEC[@]}")
[ "${#STAGED[@]}" -gt 0 ] || exit 0

WORK="$(mktemp -d "${TMPDIR:-/tmp}/jscrub-precommit.XXXXXX")"
cleanup() { find "$WORK" -depth -delete 2>/dev/null || true; }
trap cleanup EXIT

for path in "${STAGED[@]}"; do
    # Symlinks are staged as their target path, not content; skip them, as the
    # audit does by default (no --follow-symlinks).
    mode="$(git ls-files -s -- "$path" | cut -d' ' -f1)"
    [ "$mode" = "120000" ] && continue
    mkdir -p "$WORK/$(dirname -- "$path")"
    git show ":$path" > "$WORK/$path"
done

mapfile -d '' FILES < <(cd "$WORK" && find . -type f -print0)
[ "${#FILES[@]}" -gt 0 ] || exit 0

rc=0
(cd "$WORK" && "$JSCRUB" audit --quiet "${FILES[@]}") || rc=$?
[ "$rc" -eq 0 ] && exit 0

cat >&2 <<'MSG'

jscrub: staged files carry invisible Unicode (or could not be scanned); commit blocked.
  See what is there:  scripts/jscrub/jscrub inspect <file>
  Fix it by hand:     scripts/jscrub/jscrub clean --dry-run <file>   (review, then clean)
  Intentional fixture? Add it to scripts/jscrub/pathspec.sh.
MSG
exit 1
