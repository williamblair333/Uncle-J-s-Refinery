"""Behaviour matrix for lib/eval-verdict.sh — auto-maintain.sh Part B.

Why this file exists
--------------------
On 2026-08-21 the 03:00 nightly run logged `evaluation complete` for a session
whose own final message opened "Blocked — nothing was written to the stack repo."
Two defects: the agent was never rooted in the repo, and `claude -p` exiting 0
was the entire success criterion.

The fix — a required machine-readable verdict line, cross-checked against a
path-scoped delta — shipped verified only by a scratchpad harness that no longer
exists. A control with nothing asserting it still works is the same shape as the
bug it closed, so this file pins it.

Three classes of assertion:

1. **Classification.** All six branches of `classify_eval_verdict`, each pinned
   to its exact level and message. The branch ORDER is load-bearing: a missing
   verdict must lose to nothing, and `changed` must be checked against the delta.
2. **Extraction.** `extract_eval_verdict` must accept only a verdict alone on its
   own line, and must reject the same words quoted inside a sentence — an agent
   describing the format is not an agent satisfying it.
3. **Wiring.** `auto-maintain.sh` must still source the lib and must still guard
   that source fail-closed. Without this, re-inlining the logic would orphan the
   coverage above while leaving the suite green.

pytest + bash. No API calls, no network, no git writes.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "lib" / "eval-verdict.sh"
SCRIPT = REPO_ROOT / "scripts" / "auto-maintain.sh"

INFO = "INFO"
WARN = "WARN"


def classify(eval_rc, verdict, touched="", base_sha="abc1234", closing=""):
    """Drive classify_eval_verdict in a bash subshell; return [(level, msg), ...]."""
    snippet = (
        f'source "{LIB}"\n'
        f'classify_eval_verdict "{eval_rc}" "$1" "$2" "$3" "$4"\n'
    )
    res = subprocess.run(
        ["bash", "-c", snippet, "bash", verdict, touched, base_sha, closing],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    out = []
    for line in res.stdout.splitlines():
        if not line:
            continue
        level, _, msg = line.partition("\t")
        out.append((level, msg))
    return out


def extract(transcript: str, tmp_path: Path) -> str:
    f = tmp_path / "eval.txt"
    f.write_text(transcript, encoding="utf-8")
    res = subprocess.run(
        ["bash", "-c", f'source "{LIB}"\nextract_eval_verdict "$1"', "bash", str(f)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


# ── 1. Classification: the six branches ──────────────────────────────────────

def test_nonzero_exit_warns_and_wins_over_a_present_verdict():
    """A verdict parsed out of a crashed session is not evidence of anything.

    This branch is first on purpose. If it were checked after the verdict, a
    session that emitted `VERDICT: changed` and then died would be logged as a
    clean success.
    """
    out = classify(eval_rc=1, verdict="VERDICT: changed", touched="CLAUDE.md")
    assert len(out) == 1
    assert out[0][0] == WARN
    assert "exited 1" in out[0][1]


def test_missing_verdict_is_a_failure_not_a_pass():
    """The specimen bug. Silence must never reach info()."""
    out = classify(eval_rc=0, verdict="", closing="Blocked — nothing was written.")
    assert [lvl for lvl, _ in out] == [WARN, WARN]
    assert "NO VERDICT LINE" in out[0][1]
    assert "Blocked" in out[1][1], "the agent's own closing words must reach the log"


def test_missing_verdict_beats_an_untouched_tree():
    """Order check: no verdict outranks the changed/delta branch.

    Both conditions hold at once here. If the branches were reordered, this
    would be reported as a false `changed` claim rather than as a broken
    contract — a different and less alarming message for a worse problem.
    """
    out = classify(eval_rc=0, verdict="", touched="", closing="...")
    assert "NO VERDICT LINE" in out[0][1]


def test_blocked_warns_that_nothing_was_written():
    out = classify(eval_rc=0, verdict="VERDICT: blocked permission denied on CLAUDE.md")
    assert len(out) == 1
    assert out[0][0] == WARN
    assert "NOTHING WAS WRITTEN" in out[0][1]
    assert "permission denied on CLAUDE.md" in out[0][1], "the reason must survive"


def test_changed_without_a_delta_is_challenged():
    """`changed` is the only verdict that asserts a side effect, so it is the
    only one cross-checked against the tree."""
    out = classify(eval_rc=0, verdict="VERDICT: changed", touched="", base_sha="deadbee")
    assert out[0][0] == WARN
    assert "untouched since deadbee" in out[0][1]


def test_changed_with_a_delta_is_accepted():
    out = classify(eval_rc=0, verdict="VERDICT: changed", touched="CLAUDE.md\n")
    assert out == [(INFO, "changed")]


def test_no_change_required_is_legitimate():
    """Task 5 of the prompt makes this a real outcome, and it is identical by
    diff to a blocked run. That is exactly why the verdict line exists and why
    a bare delta check could not have replaced it."""
    out = classify(eval_rc=0, verdict="VERDICT: no-change-required", touched="")
    assert out == [(INFO, "no-change-required")]


# ── 2. Extraction ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "verdict",
    ["VERDICT: changed", "VERDICT: no-change-required", "VERDICT: blocked read denied"],
)
def test_extract_accepts_each_verdict_alone_on_its_line(verdict, tmp_path):
    assert extract(f"some analysis\n{verdict}\n", tmp_path) == verdict


def test_extract_rejects_a_verdict_quoted_inside_a_sentence(tmp_path):
    """An agent describing the contract has not satisfied it.

    This is the difference between a report of a block and a claim of success:
    the sentence below describes writing `changed` while saying the opposite
    happened.
    """
    transcript = "I would have written VERDICT: changed, but the write was denied.\n"
    assert extract(transcript, tmp_path) == ""


def test_extract_rejects_an_invented_verdict_word(tmp_path):
    assert extract("VERDICT: partially-done\n", tmp_path) == ""


def test_extract_takes_the_last_verdict(tmp_path):
    """A transcript may legitimately quote the menu of options before choosing."""
    transcript = (
        "VERDICT: changed\n"
        "on reflection the guard blocked me\n"
        "VERDICT: blocked edit-surface guard\n"
    )
    assert extract(transcript, tmp_path) == "VERDICT: blocked edit-surface guard"


def test_extract_returns_empty_for_a_transcript_with_no_verdict(tmp_path):
    assert extract("Blocked — nothing was written to the stack repo.\n", tmp_path) == ""


# ── 3. Wiring: the lib must still be the live path ───────────────────────────

def test_script_parses():
    res = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_lib_parses():
    res = subprocess.run(["bash", "-n", str(LIB)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_script_sources_the_lib():
    """Re-inlining must fail CI rather than silently orphan the tests above."""
    body = SCRIPT.read_text(encoding="utf-8")
    assert "lib/eval-verdict.sh" in body
    assert "classify_eval_verdict" in body
    assert "extract_eval_verdict" in body


def test_source_failure_is_fail_closed():
    """`auto-maintain.sh` runs `set -uo pipefail` with NO `set -e`.

    A failed source therefore would not abort the script: Part B would call
    undefined functions and emit nothing for the package, which reads as success
    in the log. The guard must both check readability and verify the functions
    actually landed.
    """
    body = SCRIPT.read_text(encoding="utf-8")

    # Match the shell option line itself, not the prose about it — the guard's
    # own comment names `set -e`, and a substring check would flag that.
    set_lines = [
        ln.strip() for ln in body.splitlines()
        if ln.strip().startswith("set -") and not ln.strip().startswith("#")
    ]
    assert set_lines, "expected an explicit `set -` line near the top"
    for ln in set_lines:
        flags = ln.split()[1]
        assert "e" not in flags, (
            f"{ln!r} enables errexit — revisit the fail-closed guard, whose whole "
            "premise is that a failed source does not abort this script"
        )

    assert "EVAL_READY" in body
    assert "declare -F" in body, "sourcing cleanly is not proof the functions exist"
    assert "evaluation SKIPPED" in body


def test_missing_lib_skips_part_b_loudly(tmp_path):
    """Drive the real guard block against an absent lib.

    Mirrors the script's own logic rather than importing it, because the guard
    runs before any function is available to call.
    """
    guard = f'''
        set -uo pipefail
        VERDICT_LIB="{tmp_path}/absent.sh"
        EVAL_READY=1
        if [[ -r "$VERDICT_LIB" ]] && source "$VERDICT_LIB"; then
            for _fn in extract_eval_verdict classify_eval_verdict; do
                declare -F "$_fn" >/dev/null 2>&1 || EVAL_READY=0
            done
        else
            echo "WARN cannot source"
            EVAL_READY=0
        fi
        echo "EVAL_READY=$EVAL_READY"
    '''
    res = subprocess.run(["bash", "-c", guard], capture_output=True, text=True, timeout=30)
    assert "EVAL_READY=0" in res.stdout
    assert "cannot source" in res.stdout


def test_sourced_lib_has_no_side_effects(tmp_path):
    """Sourcing must define functions and nothing else — no writes, no git, no
    output. auto-maintain.sh sources this inside a cron run."""
    marker = tmp_path / "canary"
    res = subprocess.run(
        ["bash", "-c", f'cd "{tmp_path}" && source "{LIB}" && echo OK'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.stdout.strip() == "OK"
    assert res.stderr == ""
    assert not marker.exists()
    assert list(tmp_path.iterdir()) == []
