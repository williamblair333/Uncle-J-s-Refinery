#!/usr/bin/env bash
# ralph-harness.sh — verification-gated autonomous loop for Uncle J's Refinery.
#
# Bash port of ralph-harness.ps1. Same Ralph loop pattern (Geoffrey Huntley)
# with three upgrades:
#   1. A PRD markdown file is the stable memory between iterations.
#   2. Between iterations, a done-gate asks Claude to run jcodemunch's
#      get_changed_symbols / get_untested_symbols / get_pr_risk_profile and
#      emit a one-line JSON verdict. The loop only exits when:
#          risk < RISK_THRESHOLD
#          AND untested_count == 0
#          AND the PRD's first Progress line starts with DONE.
#   3. A hard iteration cap so Ralph can't run away.
#
# Usage:
#   ./ralph-harness.sh --prd ./PRD.md [--repo /path/to/repo] \
#                      [--max-iterations 30] [--risk-threshold 0.65] \
#                      [--skip-judge] [--dry-run]
#
# Exit codes:
#   0  done-gate approved (or DONE marker when --skip-judge)
#   2  max iterations reached without a done verdict
#   1  usage / validation / tool errors

set -euo pipefail

PRD_PATH=""
REPO_PATH="$PWD"
MAX_ITERATIONS=30
RISK_THRESHOLD="0.65"
SKIP_JUDGE=0
DRY_RUN=0

usage() {
    sed -n '1,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prd)             PRD_PATH="${2:?}"; shift 2 ;;
        --repo)            REPO_PATH="${2:?}"; shift 2 ;;
        --max-iterations)  MAX_ITERATIONS="${2:?}"; shift 2 ;;
        --risk-threshold)  RISK_THRESHOLD="${2:?}"; shift 2 ;;
        --skip-judge)      SKIP_JUDGE=1; shift ;;
        --dry-run)         DRY_RUN=1; shift ;;
        -h|--help)         usage ;;
        *) echo "Unknown arg: $1" >&2; usage ;;
    esac
done

step() { printf '\n==> %s\n' "$*" >&2; }
ok()   { printf '    OK  %s\n' "$*" >&2; }
warn() { printf '    !!  %s\n' "$*" >&2; }
stop() { printf '    X   %s\n' "$*" >&2; }

[ -n "$PRD_PATH" ] || { echo "--prd is required" >&2; usage; }
[ -f "$PRD_PATH"  ] || { stop "PRD file not found: $PRD_PATH"; exit 1; }
[ -d "$REPO_PATH" ] || { stop "Repo path not found: $REPO_PATH"; exit 1; }
command -v claude >/dev/null 2>&1 || { stop "'claude' CLI not found on PATH"; exit 1; }

PRD_PATH="$(cd "$(dirname "$PRD_PATH")" && pwd)/$(basename "$PRD_PATH")"
REPO_PATH="$(cd "$REPO_PATH" && pwd)"

step "Ralph harness starting"
ok "PRD        : $PRD_PATH"
ok "Repo       : $REPO_PATH"
ok "MaxIter    : $MAX_ITERATIONS"
ok "RiskCap    : $RISK_THRESHOLD"
ok "Judge      : $([ "$SKIP_JUDGE" -eq 1 ] && echo OFF || echo ON)"
ok "DryRun     : $([ "$DRY_RUN"    -eq 1 ] && echo YES || echo NO)"

INNER_PROMPT="Follow the PRD at \"$PRD_PATH\".

Rules for this iteration:
1. Re-read the PRD from disk. Do NOT assume earlier iterations' context is in memory.
2. Consult MemPalace for prior work on this PRD topic BEFORE editing.
3. Use jcodemunch / serena for code navigation. Do not Read large files.
4. Make the smallest change that advances the PRD.
5. Update the PRD's 'Progress' section at the end with one-line status.
6. If the PRD is complete by your assessment, also write a \`DONE\` marker
   line as the FIRST line of the Progress section, then stop."

invoke_done_gate() {
    local repo="$1" threshold="$2" gate_prompt gate_output line
    gate_prompt="Run the following jcodemunch tools against the git working tree of $repo:
  get_changed_symbols()
  get_untested_symbols(changed_only=true)
  get_pr_risk_profile()

Then print EXACTLY one line of JSON (no markdown, no commentary), of shape:
{\"risk\": <float>, \"untested_count\": <int>, \"verdict\": \"done\" | \"continue\", \"why\": \"<short reason>\"}

Decide 'done' only if: risk < $threshold AND untested_count == 0 AND the
PRD's first-progress-line starts with 'DONE'."

    step "Gate: asking Claude to inspect change + risk"
    gate_output="$(cd "$repo" && claude -p "$gate_prompt" --dangerously-skip-permissions 2>&1 || true)"
    line="$(printf '%s\n' "$gate_output" | awk '/^[[:space:]]*\{/' | tail -1)"
    if [ -z "$line" ]; then
        warn "Gate did not return parseable JSON; assuming continue."
        printf '{"verdict":"continue","why":"no JSON from gate"}'
        return
    fi
    if ! printf '%s' "$line" | python3 -c "import sys,json; json.loads(sys.stdin.read())" >/dev/null 2>&1; then
        warn "JSON parse failed."
        printf '{"verdict":"continue","why":"unparseable"}'
        return
    fi
    printf '%s' "$line"
}

iter=0
start_epoch=$(date +%s)
exit_code=0
while [ "$iter" -lt "$MAX_ITERATIONS" ]; do
    iter=$((iter + 1))
    step "Iteration $iter / $MAX_ITERATIONS"

    if [ "$DRY_RUN" -eq 1 ]; then
        ok "[dry-run] would call: (cd $REPO_PATH && claude -p @<tmp> --dangerously-skip-permissions)"
    else
        tmp="$(mktemp --suffix=.md)"
        printf '%s\n' "$INNER_PROMPT" > "$tmp"
        set +e
        (cd "$REPO_PATH" && claude -p "@$tmp" --dangerously-skip-permissions)
        rc=$?
        set -e
        rm -f "$tmp"
        [ "$rc" -ne 0 ] && warn "claude exited $rc on iter $iter; continuing."
    fi

    if [ "$SKIP_JUDGE" -eq 1 ]; then
        warn "SkipJudge set; not running done-gate. Relying on PRD 'DONE' marker only."
        if grep -qE '^[[:space:]]*DONE\b' "$PRD_PATH"; then
            ok "PRD marked DONE; stopping."
            break
        fi
        continue
    fi

    gate_json="$(invoke_done_gate "$REPO_PATH" "$RISK_THRESHOLD")"
    verdict="$(printf '%s' "$gate_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('verdict','continue'))")"
    risk="$(printf '%s' "$gate_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('risk','?'))")"
    untested="$(printf '%s' "$gate_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('untested_count','?'))")"
    why="$(printf '%s' "$gate_json" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('why',''))")"
    printf '    gate: risk=%s untested=%s verdict=%s why=%s\n' "$risk" "$untested" "$verdict" "$why"

    if [ "$verdict" = "done" ]; then
        ok "Done-gate approved. Exiting loop cleanly at iter $iter."
        break
    fi
done

elapsed=$(( $(date +%s) - start_epoch ))
step "Ralph harness finished"
ok "Iterations  : $iter"
ok "Elapsed     : ${elapsed}s"
ok "Final PRD   : $PRD_PATH"

if [ "$iter" -ge "$MAX_ITERATIONS" ] && [ "$SKIP_JUDGE" -eq 0 ]; then
    # The PS1 exits 2 only when the cap is hit without a 'done' verdict.
    # With --skip-judge we may also have hit the cap; in that case the PRD
    # DONE marker is the sole signal and hitting the cap is a soft failure.
    if [ "$verdict" != "done" ]; then
        warn "Max iterations reached without a 'done' verdict. Inspect the PRD and repo diff manually."
        exit_code=2
    fi
fi
exit "$exit_code"
