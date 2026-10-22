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
# Lex the command the way bash does (a quote-aware lexer, see THE ANALYZER below;
# python3 `shlex` until 2026-10-22), collect every command bash would EXECUTE, then
# apply the rule only where `git push` is genuinely the command being invoked. Ref tokens are judged by their last component, which is the
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
#
# ── RESIDUAL (text matching cannot see these; accepted, not a sandbox) ───────
#   git push origin HEAD / "$(git branch --show-current)" while ON main
#   a command held whole in a variable or array: "${cmd[@]}", $CMD
#   code synthesised from data: bash -c "$(printf …)", base64 | bash, a script file
#   git aliases (git config alias.p push; git p origin main)

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
# Quotes, backslashes and newlines are deleted first: bash reads `pu\sh`, `p''ush`
# and a `pu\<newline>sh` continuation as `push`, and the raw text has no `push` in
# it. `$` and backticks also skip the shortcut: `$'\x70ush'`, `$P`, `$(echo push)`
# produce the word only at run time, and the analyzer treats them as unknown.
# A missing `tr` must not read as "no push" (pipefail would report grep's 1), so
# its absence also skips the shortcut.
case "$CMD" in *'$'*|*'`'*) prefilter_rc=0 ;; *)
  if command -v tr >/dev/null 2>&1; then
    printf '%s' "$CMD" | tr -d '\\\n"'"'" | grep -qi 'push'
    prefilter_rc=$?
  else
    prefilter_rc=0
  fi ;;
esac
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

# ── THE ANALYZER (2026-10-22 rewrite) ───────────────────────────────────────
# shlex knew quoting but not EXECUTION. It kept `"…$(git push origin main)…"` as
# one inert token, though bash runs that substitution, and it never looked inside
# `bash -c '…'`, `eval`, backticks, `<( )`, a heredoc fed to a shell, or past a
# newline. All of those were silent false negatives. The lexer below follows bash's
# quoting rules and collects EVERY simple command bash would execute:
#   * top-level commands split on ; & | && || ( ) and newlines
#   * $( ) and <( ) >( ) bodies, unquoted OR inside double quotes, parsed in place
#   * backtick bodies, and $( ) inside ${…} and unquoted heredoc bodies
#   * the code argument of sh/bash/zsh/… -c, the words after eval, the remote
#     command after ssh, and heredoc/herestring stdin fed to any of those
# and drops what bash does NOT execute: single-quoted text, escaped \$( ),
# quoted-delimiter heredoc bodies fed to a non-shell (the `git commit -F- <<'EOF'`
# and `-m "$(cat <<'EOF' … EOF)"` message idioms), and # comments.
# In each collected command, `git` at ANY word position (so env/sudo/xargs/timeout/
# nice/find -exec wrappers are covered without a list) followed by `push` and a
# protected ref blocks. A word bash computes at run time ($VAR, $( )) in the git or
# subcommand slot counts as git / push: unknown means block.
# Parse failure → exit 3 → the caller's regex, after a loose whole-text check here.
# Any other failure → exit 2 (block). Nesting deeper than MAX_DEPTH → block.
# The command reaches python on STDIN, the program as -c. It used to ride an env
# var (CMD="$CMD"), and exec refuses any single string over 128 KiB, so a long
# command never reached the analyzer and silently got the weaker regex.
IFS= read -r -d '' PROG <<'PY' || true
import codecs, os, re, sys

cmd = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
if not cmd.strip():
    sys.exit(0)

# git global options that consume a following value.
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# A ref token names a protected branch when that name is the token's LAST
# component. Tokenised equivalent of upstream's trailing character class:
#   main, HEAD:main, refs/heads/main, +main, +main:main   -> match
#   restore/main-reland-2026-08-14, main2, main:refs/...  -> no match
REF = re.compile(r"(?:^|[^A-Za-z0-9_])(?:main|master|production)$", re.I)
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh", "yash", "fish", "busybox"}
INTERPRETERS = {"python", "python2", "python3", "perl", "ruby", "node", "php", "pwsh", "powershell"}
INTERP_CODE_FLAGS = {"-c", "-e", "-E", "-r", "--eval", "-Command", "-command"}
class _Loose:
    """`git … push … main` anywhere, in order — the fail-closed check for text the
    lexer cannot see into. Three linear searches, not one `.*.*` regex: that one
    backtracks polynomially on a long command, and a hook timeout fails OPEN."""
    G = re.compile(r"\bgit\b", re.I)
    P = re.compile(r"\bpush\b", re.I)
    R = re.compile(r"\b(?:main|master|production)\b", re.I)

    def search(self, t):
        m = self.G.search(t)
        m = m and self.P.search(t, m.end())
        return bool(m and self.R.search(t, m.end()))


LOOSE = _Loose()
DYN = "\x00"          # stands in for text bash computes at run time
MAX_DEPTH = 8


class Unparseable(Exception):
    pass


class TooDeep(Exception):
    pass


def base(word):
    b = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return b[:-4] if b.endswith(".exe") else b


def dynamic(word):
    return DYN in word or word.startswith("$")


class Lexer:
    def __init__(self, s, depth):
        if depth > MAX_DEPTH:
            raise TooDeep()
        self.s, self.n, self.depth = s, len(s), depth
        self.cmds = []        # each: {"words": [...], "stdin": [...]}
        self.nest = 0

    def run(self):
        self.parse(0, None)
        return self.cmds

    def sub(self, i):
        """Parse a $( ) / <( ) body starting at i; return index after ')'."""
        self.nest += 1
        if self.nest > 64:
            raise TooDeep()
        try:
            return self.parse(i, ")")
        finally:
            self.nest -= 1

    def backtick(self, i, buf):
        s, n, out = self.s, self.n, []
        while i < n:
            c = s[i]
            if c == "\\" and i + 1 < n and s[i + 1] in "`$\\":
                out.append(s[i + 1]); i += 2; continue
            if c == "`":
                self.cmds.extend(Lexer("".join(out), self.depth + 1).run())
                buf.append(DYN)
                return i + 1
            out.append(c); i += 1
        raise Unparseable()

    def dq(self, i, buf, stop, end=None):
        """Double-quote rules (also ${…} and unquoted heredoc bodies)."""
        s = self.s
        n = self.n if end is None else end
        while i < n:
            c = s[i]
            if stop is not None and c == stop:
                return i + 1
            if c == "\\" and i + 1 < n:
                nx = s[i + 1]
                if nx in '$`"\\\n':
                    if nx != "\n":
                        buf.append(nx)
                    i += 2; continue
                buf.append(c); i += 1; continue
            if c == "$" and i + 1 < n and s[i + 1] == "(":
                i = self.sub(i + 2); buf.append(DYN); continue
            if c == "$" and i + 1 < n and s[i + 1] == "{":
                i = self.dq(i + 2, [], "}"); buf.append(DYN); continue
            if c == "`":
                i = self.backtick(i + 1, buf); continue
            buf.append(c); i += 1
        if stop is not None:
            raise Unparseable()
        return i

    def heredoc(self, i, rec, delim, quoted, strip):
        s, n, start = self.s, self.n, i
        body_end = n
        while i < n:
            j = s.find("\n", i)
            line_end = n if j < 0 else j
            line = s[i:line_end]
            if (line.lstrip("\t") if strip else line) == delim:
                body_end = i
                i = n if j < 0 else j + 1
                break
            i = n if j < 0 else j + 1
        if not quoted:
            self.dq(start, [], None, body_end)   # $( ) and backticks in the body run
        rec["stdin"].append(s[start:body_end])
        return i

    def parse(self, i, term):
        s, n = self.s, self.n
        rec = {"words": [], "stdin": []}
        st = {"buf": [], "inword": False, "quoted": False, "redir": False, "here": None}
        pending = []
        paren = 0

        def endword():
            if not st["inword"]:
                return
            w = "".join(st["buf"])
            here = st["here"]
            if here == "string":
                rec["stdin"].append(w)
            elif here is not None:
                pending.append((rec, w, st["quoted"], here == "strip"))
            elif not st["redir"]:
                rec["words"].append(w)
            st.update(buf=[], inword=False, quoted=False, redir=False, here=None)

        def endcmd():
            nonlocal rec
            endword()
            if rec["words"] or rec["stdin"]:
                self.cmds.append(rec)
            rec = {"words": [], "stdin": []}

        def word(text, quoted=False):
            st["buf"].append(text); st["inword"] = True
            if quoted:
                st["quoted"] = True

        while i < n:
            c = s[i]
            if c == "\\":
                if i + 1 < n and s[i + 1] == "\n":
                    i += 2; continue
                word(s[i + 1] if i + 1 < n else "\\", True); i += 2; continue
            if c == "'":
                j = s.find("'", i + 1)
                if j < 0:
                    raise Unparseable()
                word(s[i + 1:j], True); i = j + 1; continue
            if c == "$" and s.startswith("$'", i):
                j, raw = i + 2, []
                while j < n and s[j] != "'":
                    if s[j] == "\\" and j + 1 < n:
                        raw.append(s[j:j + 2]); j += 2
                    else:
                        raw.append(s[j]); j += 1
                if j >= n:
                    raise Unparseable()
                try:
                    txt = codecs.decode("".join(raw), "unicode_escape")
                except Exception:
                    txt = DYN
                word(txt, True); i = j + 1; continue
            if c == '"' or (c == "$" and s.startswith('$"', i)):
                i += 1 if c == '"' else 2
                st["inword"] = True; st["quoted"] = True
                i = self.dq(i, st["buf"], '"'); continue
            if c == "$" and s.startswith("$(", i):
                i = self.sub(i + 2); word(DYN); continue
            if c == "$" and s.startswith("${", i):
                i = self.dq(i + 2, [], "}"); word(DYN); continue
            if c == "`":
                st["inword"] = True
                i = self.backtick(i + 1, st["buf"]); continue
            if c in "<>" and i + 1 < n and s[i + 1] == "(":
                endword()
                i = self.sub(i + 2); word(DYN); continue
            if c == "#" and not st["inword"]:
                j = s.find("\n", i)
                i = n if j < 0 else j
                continue
            if c in " \t\r":
                endword(); i += 1; continue
            if c == "\n":
                endword(); i += 1
                for (r, delim, quoted, strip) in pending:
                    i = self.heredoc(i, r, delim, quoted, strip)
                pending.clear()
                endcmd(); continue
            if c == "&" and s.startswith("&>", i):
                endword(); st["redir"] = True; i += 2
                if i < n and s[i] == ">":
                    i += 1
                continue
            if c in ";&|":
                endcmd(); i += 1
                while i < n and s[i] in ";&|":
                    i += 1
                continue
            if c == "(":
                endcmd(); paren += 1; i += 1; continue
            if c == ")":
                endcmd()
                if paren == 0:
                    if term == ")":
                        return i + 1
                    i += 1; continue      # stray ')' (e.g. a case pattern): keep going
                paren -= 1; i += 1; continue
            if c in "<>":
                if st["inword"] and not st["quoted"] and "".join(st["buf"]).isdigit():
                    st.update(buf=[], inword=False)      # fd number: 2>&1
                else:
                    endword()
                if s.startswith("<<<", i):
                    st["here"] = "string"; i += 3; continue
                if s.startswith("<<", i):
                    i += 2
                    strip = i < n and s[i] == "-"
                    if strip:
                        i += 1
                    st["here"] = "strip" if strip else "doc"; continue
                i += 1
                while i < n and s[i] in ">|&":
                    i += 1
                st["redir"] = True; continue
            word(c); i += 1
        if term is not None:
            raise Unparseable()
        endword()
        for (r, delim, quoted, strip) in pending:     # heredoc with no body line
            pass
        endcmd()
        return n


def pushes_protected(words):
    # tail[i]: some word at or after i names a protected ref. Precomputed so a long
    # `git push git push …` is linear — a hook that times out fails OPEN.
    tail = [False] * (len(words) + 1)
    for i in range(len(words) - 1, -1, -1):
        t = words[i]
        tail[i] = tail[i + 1] or bool(REF.search(t) or REF.search(static(t)))
    for j, w in enumerate(words):
        if not (base(w) == "git" or dynamic(w)):
            continue
        k = j + 1
        while k < len(words) and words[k].startswith("-"):
            opt = words[k]; k += 1
            if opt in GIT_OPTS_WITH_VALUE and k < len(words):
                k += 1
        if k < len(words) and (words[k] == "push" or (dynamic(words[k]) and base(w) == "git")):
            if tail[k + 1]:
                return True
    return False


VAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-])")


def static(word):
    """The word with run-time parts removed: `main$(true)` and `main$EMPTY`
    can expand to `main`, so the protected-ref test also runs on this."""
    return VAR.sub("", word.replace(DYN, ""))


def analyze(text, depth):
    for rec in Lexer(text, depth).run():
        words = rec["words"]
        if pushes_protected(words):
            return True
        feeds_shell = evaled = False
        for j, w in enumerate(words):
            b = base(w)
            if b in SHELLS:
                feeds_shell = True
                has_c = has_operand = False
                for k in range(j + 1, len(words)):
                    if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", words[k]):
                        has_c = True
                        if k + 1 < len(words) and analyze(words[k + 1], depth + 1):
                            return True
                        break
                    if not words[k].startswith(("-", "+")):
                        has_operand = True
                        break
                # A shell with neither -c nor a script operand executes its stdin.
                # When that is a pipe (`echo "git push origin main" | bash`) the
                # code is another command's OUTPUT, which no lexer can see. Block
                # on a loose match anywhere in the text: unknown means block.
                if not has_c and not has_operand and LOOSE.search(text):
                    return True
            elif b == "source" or b == ".":
                if any(t in ("/dev/stdin", "-") or DYN in t for t in words[j + 1:j + 2]) \
                        and LOOSE.search(text):
                    return True
            elif b in ("eval", "ssh") and not evaled:
                # Only the first: its re-analysis already covers every later word,
                # and re-analysing per occurrence is exponential in `eval eval …`.
                feeds_shell = evaled = True
                if analyze(" ".join(words[j + 1:]), depth + 1):
                    return True
            elif b in INTERPRETERS:
                for k in range(j + 1, len(words) - 1):
                    if words[k] in INTERP_CODE_FLAGS and LOOSE.search(words[k + 1]):
                        return True
        if feeds_shell:
            for body in rec["stdin"]:
                if analyze(body, depth + 1):
                    return True
    return False


try:
    sys.exit(2 if analyze(cmd, 0) else 0)
except Unparseable:
    # Cannot lex it as bash would. Block on a loose whole-text match, otherwise
    # hand to the caller's regex (exit 3). Never exit 0 here -- that would fail
    # OPEN on a parse error.
    sys.exit(2 if LOOSE.search(cmd) else 3)
except TooDeep:
    sys.exit(2)
except Exception:
    sys.exit(2)
PY
printf '%s' "$CMD" | python3 -c "$PROG"

rc=$?
case "$rc" in
    0) exit 0 ;;
    2) deny ;;
    *) regex_verdict && deny; exit 0 ;;   # 3 = unparseable, or any unexpected failure
esac
