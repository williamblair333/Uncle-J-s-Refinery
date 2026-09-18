#!/usr/bin/env bash
# retrofit — inventory existing projects against the product-quality bar.
#
# Read-only by default. It finds problems and ranks them; it never fixes
# anything and never writes inside the projects it inspects (except the gate's
# own report when --run is given).
#
# Usage:
#   retrofit.sh [--root DIR] [--run] [--out FILE]
#
#   --root DIR   where to look for git repos (default /opt/proj)
#   --owner STR  only audit repos whose origin contains STR (default
#                williamblair333; pass an empty string to audit everything)
#   --run        actually execute the first-run gate for repos that have a
#                PRODUCT.md — slow, pulls images, writes .first-run-gate/
#   --out FILE   audit destination (default <root>/PRODUCT-AUDIT.md)
#
# Opt out per repo with a .no-product-gate file at its root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="/opt/proj"
RUN_GATE=0
OUT=""
# Repos whose origin does not contain this string are treated as third-party
# clones and skipped. Set --owner '' to audit everything under the root.
OWNER="${PRODUCT_AUDIT_OWNER:-williamblair333}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --run) RUN_GATE=1; shift ;;
    --owner) OWNER="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

OUT="${OUT:-$ROOT/PRODUCT-AUDIT.md}"
[[ -d "$ROOT" ]] || { printf 'no such directory: %s\n' "$ROOT" >&2; exit 2; }

printf '==> Scanning %s for git repositories\n' "$ROOT"

declare -a rank1=() rank2=() rank3=() rank4=()

while IFS= read -r gitdir; do
  repo="$(dirname "$gitdir")"
  name="$(basename "$repo")"
  [[ -f "$repo/.no-product-gate" ]] && { printf '    -- %s (opted out)\n' "$name"; continue; }

  # Someone else's clone is not your product. Judging yt-dlp for lacking a brief
  # buries the repos you are actually responsible for.
  origin_url="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
  if [[ -n "$origin_url" && -n "$OWNER" && "$origin_url" != *"$OWNER"* ]]; then
    printf '    -- %s (third-party clone: %s)\n' "$name" "${origin_url##*/}"
    continue
  fi

  has_readme=0; [[ -f "$repo/README.md" || -f "$repo/readme.md" ]] && has_readme=1

  if [[ ! -f "$repo/PRODUCT.md" ]]; then
    if [[ "$has_readme" = "0" ]]; then
      rank1+=("$name|no PRODUCT.md and no README — a stranger has nothing to start from|$repo")
    else
      rank3+=("$name|no PRODUCT.md — core job, first-run path and success measures are unstated|$repo")
    fi
    printf '    !! %s — no brief\n' "$name"
    continue
  fi

  if ! grep -q 'verify:' "$repo/PRODUCT.md" 2>/dev/null; then
    rank3+=("$name|PRODUCT.md has no verify: block — the brief cannot be checked by a machine|$repo")
    printf '    !! %s — brief not machine-checkable\n' "$name"
    continue
  fi

  if [[ "$RUN_GATE" = "1" ]]; then
    printf '    .. %s — running gate\n' "$name"
    if python3 "$SCRIPT_DIR/first_run_gate.py" "$repo" >/dev/null 2>&1; then
      printf '    OK %s — gate passes\n' "$name"
    else
      status=$?
      detail="$(python3 - "$repo/.first-run-gate/report.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    report = json.load(open(sys.argv[1]))
except Exception:
    print("gate produced no readable report"); raise SystemExit
bits = [f"{f.get('kind')}: {f.get('detail')}" for f in report.get("failures", [])]
print(report.get("reason") or "; ".join(bits) or "gate failed without a named failure")
PY
)"
      if [[ "$status" = "2" ]]; then
        rank2+=("$name|gate could not run — $detail|$repo")
      else
        rank1+=("$name|first run is broken — $detail|$repo")
      fi
      printf '    !! %s — %s\n' "$name" "$detail"
    fi
  else
    rank4+=("$name|has a brief; gate not run in this pass (use --run)|$repo")
  fi
done < <(find "$ROOT" -maxdepth 3 -type d -name .git -not -path '*/node_modules/*' 2>/dev/null | sort)

{
  printf '# Product audit\n\n'
  printf 'Generated %s by `retrofit.sh` (read-only). Root: `%s`. Gate executed: %s.\n\n' \
    "$(date -Iseconds)" "$ROOT" "$([[ "$RUN_GATE" = 1 ]] && echo yes || echo 'no — inventory only')"
  printf 'Ranked worst first: blocks first use > cannot be verified > unstated product > unchecked.\n\n'

  emit() {
    local title=$1; shift
    local -n items=$1
    printf '## %s\n\n' "$title"
    if [[ ${#items[@]} -eq 0 ]]; then
      printf '_none_\n\n'; return
    fi
    for entry in "${items[@]}"; do
      IFS='|' read -r name detail path <<< "$entry"
      printf -- '- **%s** — %s\n  `%s`\n' "$name" "$detail" "$path"
    done
    printf '\n'
  }

  emit "1. Blocks first use" rank1
  emit "2. Cannot be verified" rank2
  emit "3. Product is unstated" rank3
  emit "4. Has a brief, gate not run" rank4

  printf '## Next\n\n'
  printf -- '1. For each repo in section 3: run the `product-brief` skill.\n'
  printf -- '2. Re-run with `--run` to execute gates for repos that now have a brief.\n'
  printf -- '3. Fix section 1 first — those are broken for anyone who is not you.\n'
} > "$OUT"

printf '==> Audit written: %s\n' "$OUT"
printf '    blocks-first-use=%d  unverifiable=%d  unstated=%d  unchecked=%d\n' \
  "${#rank1[@]}" "${#rank2[@]}" "${#rank3[@]}" "${#rank4[@]}"
