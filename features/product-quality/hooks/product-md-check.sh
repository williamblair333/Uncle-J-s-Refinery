#!/usr/bin/env bash
# SessionStart notice: a project with no PRODUCT.md has never said what it is for, and its
# STANDARDS.md gaps (the expert bar) open every session, PRODUCT.md or not.
# Advisory only — it never blocks, and stays quiet outside git repos.
set -uo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -n "$repo_root" ] || exit 0

if [ -f "$repo_root/PRODUCT.md" ]; then
  report="$repo_root/.first-run-gate/report.json"
  if [ -f "$report" ]; then
    state="$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("state", "unknown"))
except Exception:
    print("unreadable")' "$report" 2>/dev/null)"
    [ "$state" = "pass" ] || printf 'product-quality: last first-run gate was %s — re-run before opening a PR\n' "$state"
  else
    printf 'product-quality: PRODUCT.md present, no gate run yet for this project\n'
  fi
else
  printf 'product-quality: no PRODUCT.md in %s — run the product-brief skill to state the core job, first-run path and success measures\n' "$(basename "$repo_root")"
fi

python3 "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../standards_check.py" --summary "$repo_root" 2>/dev/null || true
exit 0
