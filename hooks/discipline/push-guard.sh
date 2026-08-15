#!/usr/bin/env bash
# push-guard.sh — block direct pushes to main/master/production.
#
# Versioned replacement for the inline PreToolUse hook shipped in
# dwarvesf/claude-guardrails (`full/settings.json`, v0.4.0 / 65a41de). Same
# contract: read the PreToolUse payload on stdin, print `BLOCKED: ...` to stderr
# and exit 2 to block; exit 0 to allow.
#
# WHY THIS EXISTS AS A FILE
# The upstream version is a one-line regex embedded in `~/.claude/settings.json`,
# which this harness cannot read or write — so its bug could not be fixed by a PR
# and had to be applied by hand. As a repo script (the pattern already used by
# grep-guard.sh and edit-surface-guard.sh, both symlinked into ~/.claude/hooks/),
# it is versioned, testable, and CI-covered; future fixes are ordinary PRs.
#
# ── THE ORDERING BUG ─────────────────────────────────────────────────────────
# Upstream matches raw text:
#     (^|[&|;(])[[:space:]]*git[[:space:]]+push[[:space:]]+.*\b(main|master|production)([[:space:];|&)]|$)
# Two defects follow from matching text instead of parsing it:
#   1. `.*` is not anchored to the end of the segment, so it spans command
#      separators — `git push -u origin feat/x; git rev-parse main` was blocked
#      because `main` belonged to a LATER, unrelated command.
#   2. Splitting on separators happens before anything knows about quoting, so
#      `git commit -m "... git push origin main ..."` is blocked as though the
#      commit were a push. A `git commit` is not a `git push`.
# Both are the same root cause: the guard had no idea WHICH command was running.
#
# ── THE FIX ──────────────────────────────────────────────────────────────────
# Tokenise with a real POSIX lexer (python3 `shlex`), split only on UNQUOTED
# separators, then apply the rule only where `git push` is genuinely the command
# being invoked. Ref tokens are judged by their last component, which is the
# tokenised equivalent of upstream's trailing character class — it keeps
# `restore/main-reland-2026-08-14` allowed while still catching `HEAD:main`,
# `refs/heads/main` and `+main:main`.
#
# FAIL CLOSED, NEVER OPEN. Two degraded paths both fall back to the original
# regex rather than allowing:
#   * python3 absent  (e.g. a host where only bash/grep/jq exist)
#   * unbalanced quotes, which shlex cannot tokenise → python exits 3
# The fallback reintroduces the false positives, but never a false negative.
#
# ── NEWLY BLOCKED (bypasses upstream allowed; not regressions) ───────────────
#   git push origin "main"            · quoting no longer hides the ref
#   if true; then git push origin main; fi   · leading shell keywords skipped
#   x=1 git push origin main          · env-assignment prefixes skipped
#   git -C /repo push origin main     · git global options skipped
#
# ── STILL NOT BLOCKED (deliberate parity with upstream) ─────────────────────
#   git push            · no refspec; blocking it would break ordinary flows
#   git push origin main:refs/heads/backup   · pushes main TO backup; main unchanged

set -uo pipefail

PAYLOAD=$(cat)
CMD=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
[ -n "$CMD" ] || exit 0

deny() {
    echo "BLOCKED: Direct push to main/master/production. Use a feature branch and PR." >&2
    exit 2
}

# Cheap prefilter: a `git push` invocation requires the literal token `push`, so
# a command without it cannot match. This cannot cause a false negative, and it
# keeps the interpreter out of the hot path — PreToolUse fires on EVERY Bash
# call, and python3 startup (~15ms) is 6x a grep (~2.5ms).
# Only rc==1 means "grep ran and found nothing". rc>=2 means grep itself failed
# (missing, bad regex) -- treating that as "no push" would fail OPEN, so fall
# through to the analysis paths instead.
printf '%s' "$CMD" | grep -qi 'push'
prefilter_rc=$?
[ "$prefilter_rc" -eq 1 ] && exit 0

# ── Fallback: the original regex, per-segment ───────────────────────────────
# Used only when tokenisation is unavailable or impossible. Retains the
# quote-blindness false positive; retains no false negative.
# Returns 0 = block, 1 = allow. A grep failure (rc>=2: missing binary, bad
# pattern) returns 0 -- BLOCK -- because a broken matcher must not silently
# allow. With grep gone this blocks every push-bearing command, which is loud
# and recoverable; the alternative is a guard that quietly stops guarding.
regex_verdict() {
    printf '%s\n' "$CMD" | tr ';&|(' '\n\n\n\n' \
        | grep -qEi "^[[:space:]]*git[[:space:]]+push[[:space:]]+.*\b(main|master|production)([[:space:];|&)]|$)"
    local rc=$?
    [ "$rc" -eq 1 ] && return 1
    return 0
}

if ! command -v python3 >/dev/null 2>&1; then
    regex_verdict && deny
    exit 0
fi

CMD="$CMD" python3 - <<'PY'
import os, re, shlex, sys

cmd = os.environ.get("CMD", "")
if not cmd.strip():
    sys.exit(0)

# Punctuation tokens shlex emits with punctuation_chars=True.
SEPS = {";", "&", "&&", "|", "||", "(", ")", ";;", "<", ">"}
# Words that can precede the real command inside a segment.
KEYWORDS = {"then", "do", "else", "elif", "{", "!", "time", "nohup", "command", "exec"}
# git global options that consume a following value.
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}

# A ref token names a protected branch when that name is the token's LAST
# component. Tokenised equivalent of upstream's trailing character class:
#   main, HEAD:main, refs/heads/main, +main, +main:main   -> match
#   restore/main-reland-2026-08-14, main2, main:refs/...  -> no match
REF = re.compile(r"(?:^|[^A-Za-z0-9_])(?:main|master|production)$")

try:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    tokens = list(lex)
except ValueError:
    # Unbalanced quotes: cannot tokenise safely. Exit 3 so the caller falls back
    # to the regex. Never exit 0 here -- that would fail OPEN on a parse error.
    sys.exit(3)

segments, cur = [], []
for t in tokens:
    if t in SEPS:
        segments.append(cur)
        cur = []
    else:
        cur.append(t)
segments.append(cur)

for seg in segments:
    i = 0
    while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in KEYWORDS):
        i += 1
    if i >= len(seg) or os.path.basename(seg[i]) != "git":
        continue
    i += 1
    while i < len(seg) and seg[i].startswith("-"):
        opt = seg[i]
        i += 1
        if opt in GIT_OPTS_WITH_VALUE and i < len(seg):
            i += 1
    if i >= len(seg) or seg[i] != "push":
        continue
    for tok in seg[i + 1:]:
        if REF.search(tok):
            sys.exit(2)

sys.exit(0)
PY

rc=$?
case "$rc" in
    0) exit 0 ;;
    2) deny ;;
    *) regex_verdict && deny; exit 0 ;;   # 3 = unparseable, or any unexpected failure
esac
