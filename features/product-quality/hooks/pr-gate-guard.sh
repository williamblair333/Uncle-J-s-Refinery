#!/usr/bin/env bash
# PreToolUse guard: no PR without a current first-run-gate pass.
#
# Fails OPEN by design. A guard that blocks every PR on this machine when it hits
# an unforeseen case is worse than the problem it prevents, so anything the guard
# cannot establish results in an allow-with-warning — never a block.
#
# Blocks only when ALL of these hold:
#   - the tool call is `gh pr create`
#   - the project has a PRODUCT.md (no brief yet = warn, so retrofit is possible)
#   - the diff vs the base branch touches something other than docs/tests
#   - .first-run-gate/report.json is missing, failed, or older than HEAD
#
# Override: PRODUCT_GATE_OVERRIDE=1 (recorded in the message, not silent).
set -uo pipefail

INPUT="$(cat)"
command_text="$(printf '%s' "$INPUT" | python3 -c 'import json,sys
try:
    data = json.load(sys.stdin)
except Exception:
    print(""); raise SystemExit
print((data.get("tool_input") or {}).get("command", ""))' 2>/dev/null)"

case "$command_text" in
  *"gh pr create"*) ;;
  *) exit 0 ;;
esac

allow_with_note() { printf '%s\n' "product-quality: $*" >&2; exit 0; }
block() {
  printf '%s\n' "BLOCKED by product-quality gate: $*" >&2
  printf '%s\n' "Run: python3 \$STACK_ROOT/features/product-quality/first_run_gate.py ." >&2
  printf '%s\n' "Override (recorded): PRODUCT_GATE_OVERRIDE=1" >&2
  exit 2
}

if [ "${PRODUCT_GATE_OVERRIDE:-0}" = "1" ]; then
  allow_with_note "override in effect — PR created without a gate pass"
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || allow_with_note "not a git repo — gate skipped"
[ -n "$repo_root" ] || allow_with_note "not a git repo — gate skipped"
[ -f "$repo_root/PRODUCT.md" ] || allow_with_note "no PRODUCT.md yet — gate skipped (write one with the product-brief skill)"

base="$(git -C "$repo_root" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)"
changed="$(git -C "$repo_root" diff --name-only "$base"...HEAD 2>/dev/null)" || allow_with_note "cannot diff against $base — gate skipped"
[ -n "$changed" ] || allow_with_note "no changes against $base — gate skipped"

runtime_change=0
while IFS= read -r file; do
  [ -n "$file" ] || continue
  case "$file" in
    docs/*|*.md|test/*|tests/*|*_test.py|*_test.go|*.test.ts) ;;
    *) runtime_change=1; break ;;
  esac
done <<< "$changed"

[ "$runtime_change" = "1" ] || allow_with_note "docs/tests only — gate skipped"

report="$repo_root/.first-run-gate/report.json"
[ -f "$report" ] || block "no gate report found"

python3 - "$report" "$(git -C "$repo_root" rev-parse HEAD)" <<'PY' || exit $?
import json, sys
report_path, head = sys.argv[1], sys.argv[2]
try:
    with open(report_path) as fh:
        report = json.load(fh)
except Exception as exc:
    print(f"BLOCKED by product-quality gate: report unreadable ({exc})", file=sys.stderr)
    raise SystemExit(2)
state = report.get("state")
if state != "pass":
    print(f"BLOCKED by product-quality gate: last run was {state!r}", file=sys.stderr)
    for failure in report.get("failures", []):
        print(f"  - {failure.get('kind')}: {failure.get('detail')}", file=sys.stderr)
    raise SystemExit(2)
if report.get("git_head") != head:
    print("BLOCKED by product-quality gate: report is for an older commit — re-run it",
          file=sys.stderr)
    raise SystemExit(2)
PY
exit 0
