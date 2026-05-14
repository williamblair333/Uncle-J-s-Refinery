#!/usr/bin/env bash
# ralph-harness.sh — verification-gated autonomous loop for Uncle J's Refinery.
#
# Ralph loop pattern (Geoffrey Huntley)
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
#                      [--rubric ./rubric.md] [--decompose] \
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
PRE_SCRIPT=""
RUBRIC_PATH=""
DECOMPOSE=0
OUTCOMES_MAX="${OUTCOMES_MAX_ITERATIONS:-5}"
OUTCOMES_ITER=0
OUTCOMES_CONTEXT=""

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
        --pre-script)      PRE_SCRIPT="${2:?}"; shift 2 ;;
        --rubric)          RUBRIC_PATH="${2:?}"; shift 2 ;;
        --decompose)       DECOMPOSE=1; shift ;;
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
ok "PreScript  : ${PRE_SCRIPT:-(none)}"
ok "Rubric     : ${RUBRIC_PATH:-(none)}"
ok "OutcomesMax: $OUTCOMES_MAX"
ok "Decompose  : $([ "$DECOMPOSE" -eq 1 ] && echo ON || echo OFF)"

# Validate pre-script if set
if [ -n "$PRE_SCRIPT" ] && [ ! -f "$PRE_SCRIPT" ]; then
    warn "Pre-script not found: $PRE_SCRIPT"; exit 1
fi

if [ -n "$RUBRIC_PATH" ] && [ ! -f "$RUBRIC_PATH" ]; then
    stop "Rubric file not found: $RUBRIC_PATH"; exit 1
fi

if [ "$DECOMPOSE" -eq 1 ] && [ ! -f "$HOME/.claude/skills/orchestrator/SKILL.md" ]; then
    stop "orchestrator skill not found — run install-reliability.sh first"; exit 1
fi

# Helper: run the pre-script, return its stdout.
# Supports: executable (any shebang), .py (python3), .sh (bash).
# Prints [SILENT] detection to stderr, actual output to stdout.
run_pre_script() {
    local script="$1" output
    if [ -x "$script" ]; then
        output="$("$script" 2>/dev/null)"
    elif printf '%s' "$script" | grep -q '\.py$'; then
        output="$(python3 "$script" 2>/dev/null)"
    else
        output="$(bash "$script" 2>/dev/null)"
    fi
    printf '%s' "$output"
}

build_inner_prompt() {
    local outcomes_section=""
    if [ -n "$OUTCOMES_CONTEXT" ]; then
        outcomes_section="Outcomes gap from previous iteration (address these FIRST):
$OUTCOMES_CONTEXT
---

"
        OUTCOMES_CONTEXT=""  # consume it
    fi
    printf '%s%s' "$outcomes_section" "Follow the PRD at \"$PRD_PATH\".

Rules for this iteration:
1. Re-read the PRD from disk. Do NOT assume earlier iterations' context is in memory.
2. Consult MemPalace for prior work on this PRD topic BEFORE editing.
3. Use jcodemunch / serena for code navigation. Do not Read large files.
4. Make the smallest change that advances the PRD.
5. Update the PRD's 'Progress' section at the end with one-line status.
6. If the PRD is complete by your assessment, also write a \`DONE\` marker
   line as the FIRST line of the Progress section, then stop."
}

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

invoke_outcomes_check() {
    local repo="$1" rubric_path="$2"
    local orch_skill="$HOME/.claude/skills/outcomes/SKILL.md"

    if [ ! -f "$orch_skill" ]; then
        warn "outcomes skill not found at $orch_skill; skipping outcomes check"
        printf '{"verdict":"skip","why":"outcomes skill not installed"}'
        return
    fi

    local skill_content rubric_content prd_progress prompt output line tmp
    skill_content="$(cat "$orch_skill")"
    rubric_content="$(cat "$rubric_path")"
    prd_progress="$(awk '/^## Progress/{found=1} found{print}' "$PRD_PATH" | head -25)"

    prompt="<skill>
$skill_content
</skill>

<rubric>
$rubric_content
</rubric>

<current-state>
PRD Progress section:
$prd_progress
</current-state>

Evaluate the current state against the rubric. Output EXACTLY one JSON line."

    tmp="$(mktemp --suffix=.md)"
    printf '%s\n' "$prompt" > "$tmp"
    step "Outcomes: asking grader to evaluate rubric"
    output="$(cd "$repo" && claude -p "@$tmp" --dangerously-skip-permissions 2>&1 || true)"
    rm -f "$tmp"

    line="$(printf '%s\n' "$output" | awk '/^[[:space:]]*\{/' | tail -1)"
    if [ -z "$line" ]; then
        warn "Outcomes grader returned no JSON; assuming skip"
        printf '{"verdict":"skip","why":"no JSON from grader"}'
        return
    fi
    printf '%s' "$line"
}

invoke_orchestrator() {
    local repo="$1" prd_path="$2"
    local skill_content prd_content prompt tmp output manifest

    skill_content="$(cat "$HOME/.claude/skills/orchestrator/SKILL.md")"
    prd_content="$(cat "$prd_path")"

    prompt="<skill>
$skill_content
</skill>

<prd>
$prd_content
</prd>

Produce the task manifest JSON array and nothing else."

    tmp="$(mktemp --suffix=.md)"
    printf '%s\n' "$prompt" > "$tmp"
    step "Decompose: invoking orchestrator"
    output="$(cd "$repo" && claude -p "@$tmp" --dangerously-skip-permissions 2>&1 || true)"
    rm -f "$tmp"

    # Extract JSON array from output
    manifest="$(printf '%s\n' "$output" | python3 -c "
import sys, json, re
text = sys.stdin.read()
m = re.search(r'\[.*?\]', text, re.DOTALL)
if m:
    try:
        tasks = json.loads(m.group())
        print(json.dumps(tasks))
        sys.exit(0)
    except Exception:
        pass
print('[]')
" 2>/dev/null || printf '[]')"

    printf '%s' "$manifest"
}

run_decomposed() {
    local repo="$1" manifest="$2"
    local task_count decompose_dir i role task output_file
    local pids=()

    task_count="$(printf '%s' "$manifest" \
        | python3 -c "import sys,json; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)"

    if [ "$task_count" -eq 0 ]; then
        warn "Orchestrator returned empty manifest; falling back to single-agent mode"
        return 1
    fi

    step "Decompose: spawning $task_count sub-agent(s)"
    decompose_dir="$(mktemp -d --suffix=.decompose)"

    for i in $(seq 0 $((task_count-1))); do
        role="$(printf '%s' "$manifest" | python3 -c \
            "import sys,json; t=json.loads(sys.stdin.read()); print(t[$i].get('role','agent'))")"
        task="$(printf '%s' "$manifest" | python3 -c \
            "import sys,json; t=json.loads(sys.stdin.read()); print(t[$i].get('task',''))")"
        output_file="$decompose_dir/output_$i.md"

        ok "Sub-agent $i (role=$role)"
        (cd "$repo" && AGENT_ROLE="$role" MCP_TIMEOUT="${MCP_TIMEOUT:-60000}" \
            claude -p "$task" --dangerously-skip-permissions > "$output_file" 2>&1) &
        pids+=($!)
    done

    # Wait for all sub-agents
    local failed=0
    for pid in "${pids[@]}"; do
        wait "$pid" || { warn "sub-agent pid=$pid exited non-zero"; failed=$((failed+1)); }
    done
    [ "$failed" -gt 0 ] && warn "$failed sub-agent(s) failed (outputs still available for synthesis)"

    # Synthesis
    step "Decompose: synthesis agent merging $task_count outputs"
    local synth_parts="" f
    for f in "$decompose_dir"/output_*.md; do
        synth_parts+="=== $(basename "$f") ===
$(cat "$f")

"
    done

    local synth_tmp synth_output
    synth_tmp="$(mktemp --suffix=.md)"
    printf 'You are the synthesis agent. Merge the following sub-agent outputs into a single coherent deliverable. Preserve all findings; resolve any conflicts by noting them.\n\n%s\n\nProduce the merged result.\n' \
        "$synth_parts" > "$synth_tmp"
    synth_output="$(cd "$repo" && claude -p "@$synth_tmp" --dangerously-skip-permissions 2>&1 || true)"
    rm -f "$synth_tmp"
    rm -rf "$decompose_dir"

    printf '%s' "$synth_output"
}

iter=0
start_epoch=$(date +%s)
exit_code=0
while [ "$iter" -lt "$MAX_ITERATIONS" ]; do
    iter=$((iter + 1))
    step "Iteration $iter / $MAX_ITERATIONS"

    # Pre-script injection: run script, capture stdout, check for [SILENT]
    PRE_OUTPUT=""
    if [ -n "$PRE_SCRIPT" ]; then
        ok "Running pre-script: $PRE_SCRIPT"
        PRE_OUTPUT="$(run_pre_script "$PRE_SCRIPT")"
        if [ "$PRE_OUTPUT" = "[SILENT]" ]; then
            ok "Pre-script returned [SILENT] — skipping iteration (nothing to act on)"
            continue
        fi
        [ -n "$PRE_OUTPUT" ] && ok "Pre-script output: ${#PRE_OUTPUT} chars injected"
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        ok "[dry-run] would call: (cd $REPO_PATH && claude -p @<tmp> --dangerously-skip-permissions)"
        [ -n "$PRE_OUTPUT" ] && ok "[dry-run] pre-script context would be prepended to prompt"
    elif [ "$DECOMPOSE" -eq 1 ]; then
        manifest="$(invoke_orchestrator "$REPO_PATH" "$PRD_PATH")"
        if ! decompose_output="$(run_decomposed "$REPO_PATH" "$manifest")"; then
            # Fallback to single-agent if manifest was empty
            tmp="$(mktemp --suffix=.md)"
            INNER_PROMPT="$(build_inner_prompt)"
            OUTCOMES_CONTEXT=""
            printf '%s\n' "$INNER_PROMPT" > "$tmp"
            set +e
            (cd "$REPO_PATH" && claude -p "@$tmp" --dangerously-skip-permissions)
            rc=$?
            set -e
            rm -f "$tmp"
            [ "$rc" -ne 0 ] && warn "claude exited $rc on iter $iter; continuing."
        else
            ok "Decompose iteration $iter complete"
        fi
    else
        tmp="$(mktemp --suffix=.md)"
        INNER_PROMPT="$(build_inner_prompt)"
        OUTCOMES_CONTEXT=""  # subshell above can't clear parent; do it here
        if [ -n "$PRE_OUTPUT" ]; then
            printf 'Pre-script context:\n\n%s\n\n---\n\n%s\n' "$PRE_OUTPUT" "$INNER_PROMPT" > "$tmp"
        else
            printf '%s\n' "$INNER_PROMPT" > "$tmp"
        fi
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

    # Outcomes check (--rubric mode only)
    if [ -n "$RUBRIC_PATH" ] && [ "$SKIP_JUDGE" -eq 0 ]; then
        OUTCOMES_ITER=$((OUTCOMES_ITER + 1))
        if [ "$OUTCOMES_ITER" -gt "$OUTCOMES_MAX" ]; then
            warn "Outcomes max iterations ($OUTCOMES_MAX) reached; proceeding without rubric gate"
        else
            outcomes_json="$(invoke_outcomes_check "$REPO_PATH" "$RUBRIC_PATH")"
            outcomes_verdict="$(printf '%s' "$outcomes_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('verdict','skip'))")"
            outcomes_why="$(printf '%s' "$outcomes_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('why',''))")"
            outcomes_remediation="$(printf '%s' "$outcomes_json" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('remediation',''))")"
            printf '    outcomes: verdict=%s why=%s\n' "$outcomes_verdict" "$outcomes_why"
            if [ "$outcomes_verdict" = "fail" ]; then
                # Override done-gate: inject gap report as next-iteration context
                verdict="continue"
                OUTCOMES_CONTEXT="Outcomes grader gap report (iteration $iter):
$outcomes_remediation

Address all items above before the next iteration."
            fi
        fi
    fi

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
