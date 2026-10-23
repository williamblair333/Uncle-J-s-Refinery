#!/usr/bin/env bash
# PreToolUse guard — routes SOURCE-CODE exploration to jcodemunch (token + accuracy
# economy). DENIES reading/searching repo source via grep/egrep/fgrep/rg/ag/ack and
# cat/sed/head/tail. ALLOWS everything else: stdin pipes, log/state/tmp/proc targets,
# non-source files, source files OUTSIDE the repo (jcode can't help), in-place edits
# (sed -i), and ALL output redirections / heredocs (writes — incl. the pre-mortem
# audit sink and clearance-token flows).
#
# Detection is PER COMMAND-SEGMENT: a source file is only flagged when it is an argument
# to THAT segment's read-tool command. So `pytest a.py | tail -8` is allowed (a.py is
# pytest's arg; tail reads stdin), while `cat a.py | grep x` is denied (cat reads a.py).
# Behaviour is pinned by tests/test_grep_guard.py.
set -uo pipefail

# Projects root differs by platform: /opt/proj on Linux, /c/opt/proj under Git
# Bash (MSYS maps C:\ to /c). REPO_ROOT drives the "is this path inside the repo
# tree?" test below, so a wrong value does not error — it makes every absolute
# path look external and the guard silently allows what it should deny. Probe
# instead of hardcoding.
# Both spellings are treated as in-repo regardless of which platform we are on:
# the test is a containment check, and denying a path that happens not to exist
# here costs nothing, while missing one silently allows a source read.
PROJ_ROOTS="${UNCLE_J_PROJ_ROOT:+$UNCLE_J_PROJ_ROOT }/opt/proj /c/opt/proj"
# Fallback scope only. Once the payload is parsed, SESSION_ROOT (the git toplevel
# of the session's cwd, see session_repo_root below) replaces it — "this repo" in the
# block message. The projects root stays the fallback so a missing or unusable cwd
# fails closed rather than open.
REPO_ROOTS="$PROJ_ROOTS"
SESSION_ROOT=""   # held apart from the word-split list: a toplevel may contain spaces
ROOTS=()          # the in-repo roots, each in its literal AND symlink-resolved spelling
CWD_REAL=""       # the session's cwd, resolved — anchors relative operands
IN_REPO_REL=""    # set by in_repo(): the matched path relative to its root

# Symlink- and `..`-resolved spelling of an ABSOLUTE path that need not exist
# (`realpath -m`). in_repo() used to be a literal string-prefix test, so repo source
# reached through a symlink (~/.claude/hooks/discipline/grep-guard.sh -> this repo)
# or a `..` hop through an allowed dir (/tmp/../opt/proj/<repo>/x.py) looked
# external. If realpath is missing or fails, return the input unchanged: that is the
# old literal behaviour, never anything looser.
resolve_path() {
  local r
  r=$(realpath -m -- "$1" 2>/dev/null) || r=""
  if [[ "$r" == /* ]]; then printf '%s' "$r"; else printf '%s' "$1"; fi
}

# True when the path — literal OR resolved spelling — is a repo root or below one.
in_repo() {
  local p="$1" rp c r
  IN_REPO_REL=""
  rp=$(resolve_path "$p")
  for c in "$p" "$rp"; do
    for r in "${ROOTS[@]}"; do
      [[ -z "$r" ]] && continue
      if [[ "$c" == "$r" ]]; then IN_REPO_REL=""; return 0; fi
      case "$c" in "$r"/*) IN_REPO_REL="${c#"$r"/}"; return 0 ;; esac
    done
  done
  return 1
}

# True when a recursive search rooted at this path would walk a repo root
# (`grep -rn foo /opt/proj/` from a session in /opt/proj/<repo>).
is_repo_ancestor() {
  local rp r
  rp=$(resolve_path "$1"); rp="${rp%/}"
  for r in "${ROOTS[@]}"; do
    [[ -z "$r" ]] && continue
    [[ -z "$rp" ]] && return 0                       # "/" itself
    case "$r" in "$rp"/*) return 0 ;; esac
  done
  return 1
}

# Absolute spelling of a path operand, or nothing when it can't be known. `~` and
# `~/…` expand to $HOME (the guard sees the RAW command); relative operands are
# anchored at the session cwd when there is one. `~user/…` stays unknown.
abs_of() {
  local t="$1"
  case "$t" in
    "~"|"~"/*) t="${HOME:-}${t#\~}" ;;
    "~"*) return 0 ;;
  esac
  if [[ "$t" == /* ]]; then printf '%s' "$t"
  elif [[ -n "$CWD_REAL" ]]; then printf '%s' "$CWD_REAL/$t"
  fi
}

# An allowed (non-source) location, judged on where the path LANDS: the literal
# token must match ALLOWED_RE, and if it resolves into the repo, the repo-relative
# resolved remainder must match too. So state/x.py stays allowed, while
# /tmp/link.py -> <repo>/scripts/x.py and scripts/hook-blocks/../x.py do not.
allowed_loc() {
  local t="$1" a rp
  printf '%s' "$t" | grep -qE "$ALLOWED_RE" || return 1
  a=$(abs_of "$t"); [[ -z "$a" ]] && return 0
  rp=$(resolve_path "$a")
  in_repo "$rp" || return 0
  # realpath drops a trailing slash, and ALLOWED_RE needs one on `state/`.
  local rel="$IN_REPO_REL"
  [[ "$t" == */ || -d "$rp" ]] && rel="$rel/"
  printf '%s' "$rel" | grep -qE "$ALLOWED_RE"
}

# The guard sees the RAW command, so a glob operand (`docs/*.md`) arrives as a
# literal that names no file. Expand it against the session cwd, one absolute match
# per line. Prints nothing for a non-glob, an unknown cwd or no match (callers then
# use the literal rule, which is never looser). Returns 2 past GLOB_CAP matches:
# callers fail closed rather than walk a huge expansion.
GLOB_CAP=200
glob_matches() {
  local t="$1" a m n=0 out=""
  case "$t" in *[\*\?\[]*) ;; *) return 0 ;; esac
  a=$(abs_of "$t"); [[ -z "$a" ]] && return 0
  set +f
  while IFS= read -r m; do
    n=$((n + 1))
    [[ $n -gt $GLOB_CAP ]] && { set -f; return 2; }
    out+="$m"$'\n'
  done < <(compgen -G "$a" 2>/dev/null)
  set -f
  printf '%s' "$out"
  return 0
}

# True when an absolute path a read tool would open is repo source: in the repo
# (literal or resolved) with a source extension on either spelling, and not in an
# allowed location. With $2 = recursive, a directory (or anything that isn't a
# regular file) inside or above the repo counts too, since -r walks it.
reads_repo_source() {
  local p="$1" mode="${2:-}" rp
  allowed_loc "$p" && return 1
  rp=$(resolve_path "$p")
  if [[ -f "$rp" ]]; then
    { printf '%s' "$p" | grep -qE "$SRC_EXT" || printf '%s' "$rp" | grep -qE "$SRC_EXT"; } || return 1
    in_repo "$p" || in_repo "$rp"
    return
  fi
  [[ "$mode" == recursive ]] || return 1
  in_repo "$p" || in_repo "$rp" || is_repo_ancestor "$p"
}

# LOG must point at a directory that exists, so pick the root actually present.
LOG_ROOT=/opt/proj
for _cand in $PROJ_ROOTS; do
  [ -d "$_cand" ] && { LOG_ROOT="$_cand"; break; }
done
LOG="$LOG_ROOT/Uncle-J-s-Refinery/state/hook-blocks.log"

# >>> hook_log_append — keep byte-identical in every hook that writes hook-blocks.log
#     (tests/test_hook_log.py compares the copies). Inline, not sourced: a hook whose
#     library went missing would fail open.
# One record per line, and text only: GNU grep treats a file holding a NUL byte or
# invalid UTF-8 as binary and prints nothing, so a reviewer reads silence as "no
# blocks". Every C0 control byte and DEL becomes a space; invalid UTF-8 (`head -c`
# cutting a multibyte character) is dropped. Past HOOK_LOG_MAX_BYTES the log is
# ARCHIVED to <log>.YYYYMMDD, never truncated: it is not reconstructible. The rename
# is atomic, a writer still holding the old file lands in the archive, `mv -n` never
# overwrites one, and a mkdir lock (broken after 60 s) keeps rotations single-file.
hook_log_append() {
  local log=$1 rec=$2 max=${HOOK_LOG_MAX_BYTES:-1048576} clean size lock arch
  rec=$(printf '%s' "$rec" | LC_ALL=C tr '\000-\037\177' ' ')
  if command -v iconv >/dev/null 2>&1; then
    clean=$(printf '%s' "$rec" | iconv -c -f UTF-8 -t UTF-8 2>/dev/null)
    [[ -n "$clean" ]] && rec=$clean
  fi
  if [[ -f "$log" ]]; then
    size=$(wc -c < "$log" 2>/dev/null | tr -dc '0-9')
    if [[ -n "$size" && "$size" -gt "$max" ]]; then
      lock="$log.rotate.lock"
      if [[ -d "$lock" && -n "$(find "$lock" -maxdepth 0 -mmin +1 2>/dev/null)" ]]; then
        rmdir "$lock" 2>/dev/null
      fi
      if mkdir "$lock" 2>/dev/null; then
        size=$(wc -c < "$log" 2>/dev/null | tr -dc '0-9')
        if [[ -n "$size" && "$size" -gt "$max" ]]; then
          arch="$log.$(date +%Y%m%d)"
          [[ -e "$arch" ]] && arch="$log.$(date +%Y%m%d-%H%M%S)-$$"
          [[ -e "$arch" ]] || mv -n -- "$log" "$arch" 2>/dev/null
        fi
        rmdir "$lock" 2>/dev/null
      fi
    fi
  fi
  printf '%s\n' "$rec" >> "$log" 2>/dev/null || true
}
# <<< hook_log_append

# jq is required. Without it the parse below yields an empty CMD and the guard
# exits 0 — allowing every command it exists to screen. Fail loudly instead.
if ! command -v jq >/dev/null 2>&1; then
  echo "grep-guard: jq not found on PATH — guard cannot evaluate commands" >&2
  exit 1
fi

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || echo "unknown")

# Scope "the repo" to the session's own repo: jcodemunch serves the project being
# worked on, so another project's source read from this session is "outside the
# repo" (2026-10-16: /opt/proj/voice-line reads from a Refinery session were denied).
# Git Bash prints the toplevel as C:/..., which never prefix-matches the /c/...
# spelling of a command's paths and would make every path look external — fail
# open. cygpath -u normalises it; anything that still isn't absolute is discarded.
session_repo_root() {
  local cwd top
  cwd=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
  [[ -n "$cwd" && -d "$cwd" ]] || return 1
  top=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || return 1
  if command -v cygpath >/dev/null 2>&1; then
    top=$(cygpath -u "$top" 2>/dev/null) || return 1
  fi
  [[ "$top" == /?* ]] || return 1
  printf '%s' "$top"
}
SESSION_ROOT=$(session_repo_root) || SESSION_ROOT=""

if [[ -n "$SESSION_ROOT" ]]; then
  ROOTS=("$SESSION_ROOT" "$(resolve_path "$SESSION_ROOT")")
else
  for _r in $REPO_ROOTS; do ROOTS+=("$_r" "$(resolve_path "$_r")"); done
fi

# The session cwd, resolved the same way, so relative operands can be resolved
# against it. Unknown cwd leaves relative operands judged as before (in-repo).
_cwd=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
if [[ -n "$_cwd" && -d "$_cwd" ]]; then
  if command -v cygpath >/dev/null 2>&1; then _cwd=$(cygpath -u "$_cwd" 2>/dev/null) || _cwd=""; fi
  [[ "$_cwd" == /* ]] && CWD_REAL=$(resolve_path "$_cwd")
fi
unset _cwd _r

log_entry() { hook_log_append "$LOG" "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

[[ -z "${CMD:-}" ]] && exit 0

ALLOWED_RE='(/tmp/|/proc/|/var/log/|(^|[^[:alnum:]_])state/|\.log([^[:alnum:]]|$)|\.code-index|hook-blocks)'
SRC_EXT='\.(py|sh|bash|js|mjs|cjs|jsx|ts|tsx|go|rs|rb|php|java|c|h|cpp|hpp|swift|kt|lua|pl)([^[:alnum:]]|$)'

# ── Prefilter ─────────────────────────────────────────────────────────────────
# PreToolUse fires on EVERY Bash call; python3 startup (~15 ms) is paid only when the
# command could read something. Quotes, backslashes and newlines are deleted first
# (bash reads `c'a't`, `c\at` and a `ca\<newline>t` continuation as `cat`), and `$`,
# backticks and `<` skip the shortcut: `$(echo cat)`, `$X` and `done < x.py` produce
# or perform a read the raw text does not spell. Pure bash — no external binary whose
# absence could read as "no match".
case "$CMD" in
  *'$'*|*'`'*|*'<'*) ;;
  *)
    _flat=${CMD//[\\\"\']/}; _flat=${_flat//$'\n'/}
    if ! [[ "$_flat" =~ (^|[^[:alnum:]_])(e?grep|fgrep|cat|tac|nl|less|more|bat|batcat|head|tail|sed|rg|ag|ack)([^[:alnum:]_]|$) ]]; then
      exit 0
    fi ;;
esac

# ── THE ANALYZER (2026-10-23) ─────────────────────────────────────────────────
# The legacy scan below split the RAW command on spaces and on & | ; with no idea of
# quoting or of where the shell actually is. Two classes of error followed:
#   * false positives — `grep -e 'uv run example.py' f.md` read `example.py'` as a
#     file; `cd /tmp/x && cat a.py` judged a.py against the SESSION cwd;
#     `S=/tmp/…; cat $S/a.py` could not see that $S is /tmp
#   * false negatives — `cat "scripts/x.py"`-style tricks were caught only by luck,
#     and `echo "$(cat x.py)"`, `sudo cat x.py`, `bash -c 'cat x.py'`,
#     `eval cat x.py`, `grep -ex x.py` (pattern given by -e, x.py the FILE),
#     `grep -d recurse foo .`, `cat < x.py` and `ls | rg foo scripts/` were allowed,
#     and any command holding `<<` was allowed outright (`cat x.py; : <<X`).
# The analyzer lexes the command the way bash does (quoting, escapes, $( ), ` `,
# <( ), heredocs, comments), follows cd/pushd/subshells/literal VAR=value
# assignments, unwraps sudo/env/xargs/timeout/… and sh -c / eval / heredoc-fed
# shells, parses grep/sed/head/tail/cat/rg option syntax, and prints one record per
# path a read tool would open:
#     F <cwd> <path>   read as a file           R <cwd> <path>   walked recursively
#     C <cwd>          the cwd itself walked    D <why>          deny outright
# <cwd> is one POSSIBLE working directory (empty = unknown); a path that is unsafe
# under ANY possible cwd is denied. The bash helpers above judge each record, so
# symlink/`..`/glob/allowed-location handling is shared with the legacy path.
# Where the shell's state can't be known the analyzer assumes the worst: a cd that
# may fail leaves BOTH directories possible; a variable it can't resolve makes the
# word dynamic, and a dynamic word with a source extension is denied.
# Exit 0 = records printed (possibly none). Anything else — python3 absent, a parse
# failure (exit 3), a crash — falls back to the legacy scan, after the analyzer's
# own whole-text check for an unparseable command (exit 2 = deny).
# RESIDUAL (accepted; this is a token-routing guard, not a sandbox): interpreters
# (`python3 -c "open('x.py')"`, awk, less, nl, …), git show/grep, a command held in
# a variable or array, code produced at run time (base64 | bash), and an xargs/find
# whose file list arrives on stdin from outside the repo but is judged by cwd.
IFS= read -r -d '' GG_PROG <<'PY' || true
import codecs, os, posixpath, re, sys

cmd = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
SESSION_CWD = sys.argv[1] if len(sys.argv) > 1 else ""
HOME = os.environ.get("HOME", "")

DYN = "\x00"                       # text bash computes at run time
VO, VC = "\x01", "\x02"            # \x01NAME\x02 = an unresolved $NAME
MAX_DEPTH = 8
CAT_LIKE = {"cat", "tac", "nl", "less", "more", "bat", "batcat"}
READ_TOOLS = {"grep", "egrep", "fgrep", "head", "tail", "sed", "rg", "ag", "ack"} | CAT_LIKE
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh", "yash", "busybox"}
OPEN_KW = {"if", "while", "until", "for", "case", "select"}
CLOSE_KW = {"fi", "done", "esac"}
SKIP_KW = {"then", "else", "elif", "do", "!", "{", "}", "time", "coproc", "in"}
SRC_EXT = re.compile(r"\.(py|sh|bash|js|mjs|cjs|jsx|ts|tsx|go|rs|rb|php|java|c|h|cpp|hpp|swift|kt|lua|pl)([^A-Za-z0-9]|$)")
ALLOWED = re.compile(r"(/tmp/|/proc/|/var/log/|(^|[^A-Za-z0-9_])state/|\.log([^A-Za-z0-9]|$)|\.code-index|hook-blocks)")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)$", re.S)
LOOSE_TOOL = re.compile(r"(^|[^A-Za-z0-9_])(e?grep|fgrep|cat|tac|nl|less|more|bat|batcat|head|tail|sed|rg|ag|ack)([^A-Za-z0-9_]|$)")


class Unparseable(Exception):
    pass


class TooDeep(Exception):
    pass


def loose(text):
    """A read tool and a source-looking name anywhere in the text — the fail-closed
    check for text whose execution the lexer cannot see."""
    flat = re.sub(r"[\\\"'\n]", "", text)
    return bool(LOOSE_TOOL.search(flat) and SRC_EXT.search(flat))


def base(word):
    b = word.replace("\\", "/").rsplit("/", 1)[-1]
    return b[:-4] if b.lower().endswith(".exe") else b


# ── Lexer (bash quoting; shared shape with push-guard.sh's) ────────────────────
class Lexer:
    """Produces a flat item list: ("cmd", rec) | ("op", ";"|"&&"|"||"|"|"|"&")
    | ("open",) | ("close",). rec = {"words", "in", "stdin"}. Substitution bodies
    appear as open … close around their commands, before the command using them."""

    def __init__(self, s, depth):
        if depth > MAX_DEPTH:
            raise TooDeep()
        self.s, self.n, self.depth = s, len(s), depth
        self.items = []
        self.nest = 0
        self.funcdef = False

    def run(self):
        self.parse(0, None)
        return self.items

    def sub(self, i):
        self.nest += 1
        if self.nest > 64:
            raise TooDeep()
        self.items.append(("open",))
        try:
            j = self.parse(i, ")")
        finally:
            self.nest -= 1
        self.items.append(("close",))
        return j

    def backtick(self, i, buf):
        s, n, out = self.s, self.n, []
        while i < n:
            c = s[i]
            if c == "\\" and i + 1 < n and s[i + 1] in "`$\\":
                out.append(s[i + 1]); i += 2; continue
            if c == "`":
                inner = Lexer("".join(out), self.depth + 1)
                self.items.append(("open",))
                self.items.extend(inner.run())
                self.items.append(("close",))
                self.funcdef = self.funcdef or inner.funcdef
                buf.append(DYN)
                return i + 1
            out.append(c); i += 1
        raise Unparseable()

    def var(self, i, buf):
        """At s[i] == '$' (not $( $' $"); returns new i."""
        s, n = self.s, self.n
        j = i + 1
        if j < n and (s[j].isalpha() or s[j] == "_"):
            k = j
            while k < n and (s[k].isalnum() or s[k] == "_"):
                k += 1
            buf.append(VO + s[j:k] + VC)
            return k
        if j < n and (s[j].isdigit() or s[j] in "@*#?$!-"):
            buf.append(DYN)
            return j + 1
        if j < n and s[j] == "{":
            m = re.match(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", s[j:])
            if m:
                buf.append(VO + m.group(1) + VC)
                return j + m.end()
            k = self.dq(j + 1, [], "}")
            buf.append(DYN)
            return k
        buf.append("$")
        return j

    def dq(self, i, buf, stop, end=None):
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
            if c == "$":
                i = self.var(i, buf); continue
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
            self.dq(start, [], None, body_end)     # $( ) and backticks in the body run
        rec["stdin"].append(s[start:body_end])
        return i

    def parse(self, i, term):
        s, n = self.s, self.n
        rec = {"words": [], "in": [], "stdin": []}
        st = {"buf": [], "inword": False, "quoted": False, "redir": None, "here": None,
              "lead_q": False}
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
            elif st["redir"] == "in":
                rec["in"].append(w)
            elif st["redir"] is None:
                # A quoted leading ~ is literal: `cat "~/x.py"` reads ./~/x.py.
                if st["lead_q"] and w.startswith("~"):
                    w = "./" + w
                rec["words"].append(w)
            st.update(buf=[], inword=False, quoted=False, redir=None, here=None, lead_q=False)

        def endcmd():
            nonlocal rec
            endword()
            if rec["words"] or rec["stdin"] or rec["in"]:
                self.items.append(("cmd", rec))
            rec = {"words": [], "in": [], "stdin": []}

        def word(text, quoted=False):
            if not st["inword"] and quoted:
                st["lead_q"] = True
            st["buf"].append(text); st["inword"] = True
            if quoted:
                st["quoted"] = True

        def op(o):
            endcmd()
            self.items.append(("op", o))

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
                if not st["inword"]:
                    st["lead_q"] = True
                i += 1 if c == '"' else 2
                st["inword"] = True; st["quoted"] = True
                i = self.dq(i, st["buf"], '"'); continue
            if c == "$" and s.startswith("$(", i):
                i = self.sub(i + 2); word(DYN); continue
            if c == "$":
                st["inword"] = True
                i = self.var(i, st["buf"]); continue
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
                op(";"); continue
            if c == "&" and s.startswith("&>", i):
                endword(); st["redir"] = "out"; i += 2
                if i < n and s[i] == ">":
                    i += 1
                continue
            if c in ";&|":
                j = i
                while j < n and s[j] in ";&|":
                    j += 1
                run = s[i:j]
                if "||" in run:
                    o = "||"
                elif "&&" in run:
                    o = "&&"
                elif "|" in run:
                    o = "|"
                elif run == "&":
                    o = "&"
                else:
                    o = ";"
                op(o); i = j; continue
            if c == "(":
                # `name()` / `name ()` is a function definition: its body runs only
                # when called, by a name the guard can't follow. Flag it.
                if s.startswith("()", i) or re.match(r"\(\s*\)", s[i:]):
                    self.funcdef = True
                op(";"); self.items.append(("open",)); paren += 1; i += 1; continue
            if c == ")":
                endcmd()
                if paren == 0:
                    if term == ")":
                        return i + 1
                    self.items.append(("close",))      # stray ')' (case pattern)
                    i += 1; continue
                self.items.append(("close",))
                paren -= 1; i += 1; continue
            if c in "<>":
                fd_in = c == "<"
                if st["inword"] and not st["quoted"] and "".join(st["buf"]).isdigit():
                    st.update(buf=[], inword=False)          # fd number: 2>&1
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
                j = i + 1
                while j < n and s[j] in ">|&":
                    j += 1
                if fd_in and s[i + 1:j].endswith("&"):
                    fd_in = False                            # <&3 duplicates an fd
                i = j
                st["redir"] = "in" if fd_in else "out"; continue
            word(c); i += 1
        if term is not None:
            raise Unparseable()
        endword()
        endcmd()
        return n


# ── State: possible working directories and literal variables ─────────────────
RISKY = ("RISKY",)    # a variable that may hold a file name read from somewhere


class State:
    def __init__(self, cwds, vars_):
        self.cwds = set(cwds)          # "" = unknown
        self.vars = dict(vars_)        # name -> literal value, or None = unknown

    def copy(self):
        return State(self.cwds, self.vars)

    def merge(self, other):
        out = State(self.cwds | other.cwds, {})
        for k in set(self.vars) | set(other.vars):
            a, b = self.vars.get(k, None), other.vars.get(k, None)
            if a is RISKY or b is RISKY:
                out.vars[k] = RISKY
            else:
                out.vars[k] = a if (k in self.vars and k in other.vars and a == b) else None
        return out


def expand(word, state):
    """Replace \x01NAME\x02 by the variable's literal value, or DYN when unknown."""
    def rep(m):
        name = m.group(1)
        if name in state.vars:
            v = state.vars[name]
            if v is RISKY:
                return DYN + ".py"         # may name source: judged as source
            return DYN if v is None else v
        if name == "HOME" and HOME:
            return HOME
        return DYN
    # bash expands ~ from $HOME, which the command itself may have reassigned.
    if (word == "~" or word.startswith("~/")) and "HOME" in state.vars:
        h = state.vars["HOME"]
        word = (DYN if (h is None or h is RISKY) else h) + word[1:]
    return re.sub("\x01([A-Za-z_][A-Za-z0-9_]*)\x02", rep, word)


def brace_expand(word, cap=64):
    """bash brace expansion (`{cat,x.py}`, `a{b,c}d`), capped; a word without a
    comma inside braces is returned unchanged."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", word)
    if not m:
        return [word]
    out = []
    for alt in m.group(1).split(","):
        for w in brace_expand(word[:m.start()] + alt + word[m.end():], cap):
            out.append(w)
            if len(out) >= cap:
                return out
    return out


def cd_target(state, args, home_ok=True):
    """The set of cwds after `cd ARGS` succeeds."""
    phys = False
    rest = []
    for a in args:
        if not rest and a.startswith("-") and a not in ("-", "--") and len(a) > 1:
            phys = phys or "P" in a
            continue
        if not rest and a == "--":
            continue
        rest.append(a)
    if not rest:
        if "HOME" in state.vars:
            h = state.vars["HOME"]
            return {""} if (h is None or h is RISKY or not h.startswith("/")) else {posixpath.normpath(h)}
        return {HOME} if (HOME and home_ok) else {""}
    t = rest[0]
    if DYN in t or t == "-" or t.startswith("+"):
        return {""}
    if t == "~" or t.startswith("~/"):
        if not HOME:
            return {""}
        t = HOME + t[1:]
    elif t.startswith("~"):
        return {""}
    if phys and ".." in t.split("/"):
        return {""}
    if t.startswith("/"):
        return {posixpath.normpath(t)}
    if os.environ.get("CDPATH") or "CDPATH" in state.vars:
        return {""}                      # a relative cd may land anywhere on CDPATH
    out = set()
    for c in state.cwds:
        out.add("" if not c else posixpath.normpath(posixpath.join(c, t)))
    return out


# ── Per-tool option parsing → operands ────────────────────────────────────────
def short_cluster(tok, with_arg, words, k):
    """Walk a short-option cluster. Returns (letters, value, next_k): the letter whose
    value was consumed (attached or next word), or None."""
    letters = []
    for idx, ch in enumerate(tok[1:], start=1):
        if ch in with_arg:
            rest = tok[idx + 1:]
            if rest:
                return letters + [ch], (ch, rest), k + 1
            if k + 1 < len(words):
                return letters + [ch], (ch, words[k + 1]), k + 2
            return letters + [ch], (ch, ""), k + 1
        letters.append(ch)
    return letters, None, k + 1


def parse_grep(words):
    """-> dict(recursive, operands, pattern_files, includes)."""
    out = {"recursive": False, "operands": [], "pattern_files": [], "includes": []}
    pattern_given = False
    pos = []
    k = 0
    with_arg = "efABCmdD"
    long_arg = {"--regexp", "--file", "--after-context", "--before-context", "--context",
                "--max-count", "--directories", "--devices", "--include", "--exclude",
                "--exclude-dir", "--exclude-from", "--label", "--binary-files",
                "--group-separator"}
    while k < len(words):
        t = words[k]
        if t == "--":
            pos.extend(words[k + 1:]); break
        if t.startswith("--"):
            name, eq, val = t.partition("=")
            if name in long_arg and not eq:
                val = words[k + 1] if k + 1 < len(words) else ""
                k += 2
            else:
                k += 1
            if name in ("--recursive", "--dereference-recursive"):
                out["recursive"] = True
            elif name == "--directories" and val == "recurse":
                out["recursive"] = True
            elif name == "--regexp":
                pattern_given = True
            elif name == "--file":
                pattern_given = True; out["pattern_files"].append(val)
            elif name == "--include":
                out["includes"].append(val)
            continue
        if t.startswith("-") and len(t) > 1:
            letters, val, k = short_cluster(t, with_arg, words, k)
            if "r" in letters or "R" in letters:
                out["recursive"] = True
            if val:
                ch, v = val
                if ch == "e":
                    pattern_given = True
                elif ch == "f":
                    pattern_given = True; out["pattern_files"].append(v)
                elif ch == "d" and v == "recurse":
                    out["recursive"] = True
            continue
        pos.append(t); k += 1
    out["operands"] = pos if pattern_given else pos[1:]
    return out


def parse_sed(words):
    """-> (in_place, operands, script_files)."""
    pos, files, script_given, k = [], [], False, 0
    while k < len(words):
        t = words[k]
        if t == "--":
            pos.extend(words[k + 1:]); break
        if t.startswith("--"):
            name, eq, val = t.partition("=")
            if name == "--in-place":
                return True, [], []
            if name in ("--expression", "--file", "--line-length") and not eq:
                val = words[k + 1] if k + 1 < len(words) else ""
                k += 2
            else:
                k += 1
            if name == "--expression":
                script_given = True
            elif name == "--file":
                script_given = True; files.append(val)
            continue
        if t.startswith("-") and len(t) > 1:
            letters, val, k = short_cluster(t, "efl", words, k)
            if "i" in letters:
                return True, [], []
            if val and val[0] == "e":
                script_given = True
            elif val and val[0] == "f":
                script_given = True; files.append(val[1])
            continue
        pos.append(t); k += 1
    return False, (pos if script_given else pos[1:]), files


def parse_plain(words, with_arg="", long_arg=()):
    """cat/head/tail: every non-option word is a file."""
    pos, k = [], 0
    while k < len(words):
        t = words[k]
        if t == "--":
            pos.extend(words[k + 1:]); break
        if t.startswith("--"):
            name, eq, _ = t.partition("=")
            k += 2 if (name in long_arg and not eq) else 1
            continue
        if t.startswith("-") and len(t) > 1:
            _, _, k = short_cluster(t, with_arg, words, k)
            continue
        pos.append(t); k += 1
    return [p for p in pos if p != "-"]


def parse_rg(words, tool):
    """-> (paths, globs, files_mode, pattern_files)."""
    pattern_given, files_mode = False, False
    pos, globs, pfiles, k = [], [], [], 0
    val_opts = {"-t", "-T", "--type", "--type-not", "-A", "-B", "-C", "-m", "--max-count",
                "-j", "--threads", "-M", "--max-columns", "--max-depth", "-d", "--depth",
                "--ignore-file", "--pre", "-E", "--encoding", "--sort", "--sortr",
                "--context", "--after-context", "--before-context", "-r", "--replace"}
    if tool != "rg":
        val_opts -= {"-r", "--replace", "-d"}
    while k < len(words):
        t = words[k]
        if t == "--":
            pos.extend(words[k + 1:]); break
        nxt = words[k + 1] if k + 1 < len(words) else ""
        if t in ("-g", "--glob", "--iglob", "-G"):
            globs.append(nxt); k += 2; continue
        if t.startswith(("--glob=", "--iglob=")):
            globs.append(t.split("=", 1)[1]); k += 1; continue
        if t in ("-e", "--regexp"):
            pattern_given = True; k += 2; continue
        if t in ("-f", "--file"):
            pattern_given = True; pfiles.append(nxt); k += 2; continue
        if t.startswith(("--regexp=",)):
            pattern_given = True; k += 1; continue
        if t.startswith("--file="):
            pattern_given = True; pfiles.append(t.split("=", 1)[1]); k += 1; continue
        if t == "--files":
            files_mode = True; k += 1; continue
        if t in val_opts:
            k += 2; continue
        if t.startswith("-") and len(t) > 1:
            k += 1; continue
        pos.append(t); k += 1
    paths = pos if (pattern_given or files_mode) else pos[1:]
    return paths, globs, pfiles


# ── Wrappers ──────────────────────────────────────────────────────────────────
def unwrap(words, cmd_cwds):
    """Strip command-position wrappers. Returns (words, flags, cwds) where flags may
    hold 'xargs', and cwds is overridden by env -C / sudo -D."""
    flags = set()
    cwds = cmd_cwds
    k = 0
    for _ in range(16):
        if k >= len(words):
            break
        w = base(words[k])
        if ASSIGN.match(words[k]):
            k += 1; continue
        if w in ("sudo", "doas"):
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if o in ("-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-T", "-D", "--chdir",
                         "--user", "--group", "--host", "--prompt"):
                    if o in ("-D", "--chdir") and k < len(words):
                        cwds = {"" if DYN in words[k] else words[k]} if words[k].startswith("/") else {""}
                    k += 1
            continue
        if w == "command":
            if k + 1 < len(words) and words[k + 1] in ("-v", "-V"):
                return [], flags, cwds
            k += 1
            while k < len(words) and words[k] == "-p":
                k += 1
            continue
        if w == "watch":
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if o in ("-n", "--interval", "-d", "-q", "--equexit"):
                    if o in ("-n", "--interval", "-q", "--equexit"):
                        k += 1
            continue
        if w in ("builtin", "nohup", "exec", "time"):
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if w == "exec" and o == "-a":
                    k += 1
            continue
        if w == "nice":
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if o in ("-n", "--adjustment"):
                    k += 1
            continue
        if w in ("ionice", "chrt", "taskset", "stdbuf"):
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if len(o) == 2 and o[1] in "cnpioe":
                    k += 1
            if w in ("chrt", "taskset") and k < len(words):
                k += 1
            continue
        if w == "timeout":
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if o in ("-s", "--signal", "-k", "--kill-after"):
                    k += 1
            k += 1                                    # DURATION
            continue
        if w == "env":
            k += 1
            while k < len(words):
                o = words[k]
                if o in ("-i", "-0", "--ignore-environment", "--null", "-v", "--debug"):
                    k += 1
                elif o in ("-u", "--unset"):
                    k += 2
                elif o in ("-C", "--chdir") or o.startswith("--chdir="):
                    d = o.split("=", 1)[1] if "=" in o else (words[k + 1] if k + 1 < len(words) else "")
                    k += 1 if "=" in o else 2
                    cwds = {posixpath.normpath(d)} if (d.startswith("/") and DYN not in d) else {""}
                elif o in ("-S", "--split-string") or o.startswith("--split-string="):
                    return None, flags, cwds          # caller: re-lex unknown → loose
                elif ASSIGN.match(o):
                    k += 1
                else:
                    break
            continue
        if w == "xargs":
            flags.add("xargs")
            k += 1
            while k < len(words) and words[k].startswith("-"):
                o = words[k]; k += 1
                if o in ("-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a", "--arg-file",
                         "--max-args", "--max-procs", "--delimiter", "--max-chars"):
                    if o in ("-a", "--arg-file") and k < len(words):
                        flags.add("argfile:" + words[k])
                    k += 1
            continue
        break
    return words[k:], flags, cwds


# ── Analysis ──────────────────────────────────────────────────────────────────
class Analyzer:
    def __init__(self):
        self.records = []
        self.text_all = cmd

    def emit(self, kind, cwds, path=None):
        if kind == "D":
            self.records.append(("D", "", path or "deny"))
            return
        if path is not None:
            if "\n" in path or "\x1f" in path or VO in path:
                self.records.append(("D", "", "unrepresentable path"))
                return
            if DYN in path:
                # Unknown at guard time. A source extension, or a recursive walk of an
                # unknown place, is denied; anything else stays allowed (unknowable).
                if kind != "F" or SRC_EXT.search(path.replace(DYN, "")):
                    self.records.append(("D", "", "dynamic path"))
                return
            if path.startswith(("/", "~")):
                cwds = {""}
        for c in sorted(cwds):
            self.records.append((kind, c, "" if path is None else path))

    def judge_tool(self, tool, args, cwds, piped_in, flags, dynamic_tool):
        if "xargs" in flags:
            # The file list arrives on stdin (or an -a file): judge the cwd.
            for f in flags:
                if f.startswith("argfile:"):
                    self.emit("F", cwds, f.split(":", 1)[1])
            self.emit("C", cwds)
            return
        if dynamic_tool:
            recursive = any(re.fullmatch(r"-[A-Za-z]*[rR][A-Za-z]*|--recursive|--dereference-recursive", a)
                            for a in args)
            for a in args:
                if not a.startswith("-"):
                    self.emit("R" if recursive else "F", cwds, a)
            return
        if tool in ("grep", "egrep", "fgrep"):
            g = parse_grep(args)
            for f in g["pattern_files"]:
                self.emit("F", cwds, f)
            if g["recursive"]:
                if g["includes"] and all(ALLOWED.search(i) for i in g["includes"]):
                    return
                if not g["operands"]:
                    self.emit("C", cwds)
                for o in g["operands"]:
                    self.emit("R", cwds, o)
            else:
                for o in g["operands"]:
                    self.emit("F", cwds, o)
        elif tool == "sed":
            in_place, ops, files = parse_sed(args)
            if in_place:
                return
            for o in ops + files:
                self.emit("F", cwds, o)
        elif tool in CAT_LIKE:
            for o in parse_plain(args, "vbsw" if tool == "nl" else "",
                                 ("--line-range", "--language", "--style") if tool.startswith("bat") else ()):
                self.emit("F", cwds, o)
        elif tool in ("head", "tail"):
            for o in parse_plain(args, "nc" + ("s" if tool == "tail" else ""),
                                 ("--lines", "--bytes", "--sleep-interval", "--pid")):
                self.emit("F", cwds, o)
        elif tool in ("rg", "ag", "ack"):
            paths, globs, pfiles = parse_rg(args, tool)
            for f in pfiles:
                self.emit("F", cwds, f)
            if globs and all(ALLOWED.search(x) for x in globs):
                return
            if not paths:
                if not piped_in:
                    self.emit("C", cwds)
                return
            for p in paths:
                self.emit("R", cwds, p)

    def find_exec(self, words, cwds):
        """find PATHS … -exec TOOL … {} ; — TOOL reads what find walks."""
        starts = []
        k = 1
        while k < len(words) and not words[k].startswith(("-", "(", "!")):
            starts.append(words[k]); k += 1
        while k < len(words):
            if words[k] in ("-exec", "-execdir", "-ok", "-okdir"):
                j = k + 1
                sub = []
                while j < len(words) and words[j] not in (";", "+"):
                    sub.append(words[j]); j += 1
                if sub and base(sub[0]) in READ_TOOLS:
                    if not starts:
                        self.emit("C", cwds)
                    for s0 in starts:
                        self.emit("R", cwds, s0)
                k = j + 1
                continue
            k += 1

    def run(self, text, depth, state):
        lx = Lexer(text, depth)
        items = lx.run()
        if lx.funcdef or re.search(r"(^|[;&|(\s])(function\s+\w|alias\s|shopt\s+-s\s+expand_aliases)", text):
            # A function/alias runs code under a name the guard can't follow.
            if loose(text):
                self.emit("D", None, "function or alias wrapping a read")
            state = State({""} | state.cwds, {k: None for k in state.vars})
        self.walk(items, depth, state, text)

    def walk(self, items, depth, state, text):
        stack = []
        cur = state
        ctl = 0
        chain_or = False
        prev_op = None
        last = None          # (old_state, success_state, may_fail, definite, in_pipe)
        for idx, it in enumerate(items):
            kind = it[0]
            if kind == "open":
                stack.append((cur.copy(), ctl, chain_or, prev_op))
                chain_or = False; last = None; prev_op = None
                continue
            if kind == "close":
                if stack:
                    cur, ctl, chain_or, prev_op = stack.pop()
                else:
                    cur = State({""} | cur.cwds, {k: None for k in cur.vars})
                last = (cur.copy(), cur.copy(), False, True, False)
                continue
            if kind == "op":
                o = it[1]
                if last is not None:
                    old, succ, may_fail, definite, in_pipe = last
                    if in_pipe or o in ("|", "&"):
                        # A pipeline stage's effects stay in its subshell — but the
                        # stage may be `while read f; do …; done`, whose body shares
                        # it. RISKY taint is kept (never loosens a verdict).
                        cur = old.copy()
                        for k, v in succ.vars.items():
                            if v is RISKY:
                                cur.vars[k] = RISKY
                    elif o == "&&" and not chain_or:
                        cur = succ
                    elif may_fail or not definite:
                        cur = old.merge(succ)
                    else:
                        cur = succ
                if o == "||":
                    chain_or = True
                elif o in (";", "&"):
                    chain_or = False
                prev_op = o
                last = None
                continue
            rec = it[1]
            nxt = None
            for later in items[idx + 1:]:
                if later[0] == "op":
                    nxt = later[1]
                    break
                if later[0] in ("open", "close"):
                    break
            in_pipe = prev_op == "|" or nxt in ("|", "&")
            definite = ctl == 0 and prev_op not in ("&&", "||")
            old = cur.copy()
            succ, may_fail = self.command(rec, depth, cur, prev_op == "|", text)
            words0 = [w for w in rec["words"]]
            if words0 and words0[0] in OPEN_KW:
                ctl += 1
            if words0 and words0[0] in CLOSE_KW:
                ctl = max(0, ctl - 1)
            last = (old, succ, may_fail, definite, in_pipe)

    def command(self, rec, depth, cur, piped_in, text):
        """Judge one simple command; return (state if it succeeds, may_fail)."""
        raw = rec["words"]
        # `for NAME in LIST` / `select`: NAME takes each LIST word. If any could name
        # source (a source extension, a glob, or run-time text) the loop variable is
        # RISKY — a read of it is judged as a source read.
        if len(raw) >= 2 and raw[0] in ("for", "select"):
            succ = cur.copy()
            items = [expand(w, cur) for w in raw[3:]] if len(raw) > 2 and raw[2] == "in" else [DYN]
            risky = any(DYN in w or SRC_EXT.search(w) or re.search(r"[*?\[]", w) for w in items)
            succ.vars[raw[1]] = RISKY if risky else None
            return succ, False
        words = [x for w in raw for x in brace_expand(expand(w, cur))]
        # Leading keywords (`if cat x.py; then`, `! grep …`, `{ cat x; }`).
        while words and (words[0] in SKIP_KW or words[0] in OPEN_KW or words[0] in CLOSE_KW):
            if words[0] == "case":
                words = []
                break
            words = words[1:]
        # `read NAME…` / mapfile: the names come from input the guard can't see.
        if words and base(words[0]) in ("read", "mapfile", "readarray"):
            succ = cur.copy()
            for w in words[1:]:
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", w):
                    succ.vars[w] = RISKY
            if not any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", w) for w in words[1:]):
                succ.vars["REPLY"] = RISKY
            for f in rec["in"]:
                self.emit("F", cur.cwds, expand(f, cur))
            return succ, False
        lead = words
        # Pure assignments: update literal variables.
        if words and all(ASSIGN.match(w) for w in words):
            succ = cur.copy()
            for w in words:
                name, val = ASSIGN.match(w).groups()
                succ.vars[name] = None if (DYN in val or "+=" in w.split("=", 1)[0] + "=") else val
            for f in rec["in"]:
                self.emit("F", cur.cwds, expand(f, cur))
            return succ, False
        if words and base(words[0]) in ("export", "declare", "typeset", "local", "readonly"):
            succ = cur.copy()
            for w in words[1:]:
                m = ASSIGN.match(w)
                if m:
                    succ.vars[m.group(1)] = None if DYN in m.group(2) else m.group(2)
            return succ, False
        if words and base(words[0]) == "unset":
            succ = cur.copy()
            for w in words[1:]:
                if not w.startswith("-"):
                    succ.vars[w] = None
            return succ, False
        if words and base(words[0]) in ("cd", "pushd"):
            succ = cur.copy()
            succ.cwds = cd_target(cur, words[1:])
            return succ, True
        if words and base(words[0]) == "popd":
            succ = cur.copy()
            succ.cwds = {""}
            return succ, True

        inner, flags, cwds = unwrap(words, cur.cwds)
        if inner is None:
            if loose(" ".join(words)):
                self.emit("D", None, "env -S")
            return cur, False
        if rec["in"]:
            judged = not inner or base(inner[0]) in READ_TOOLS or DYN in inner[0] \
                or base(inner[0]) in SHELLS or base(inner[0]) in ("while", "read", "mapfile", "readarray")
            if not inner and not lead:
                judged = True
            if judged:
                for f in rec["in"]:
                    self.emit("F", cwds, expand(f, cur))
        if not inner:
            return cur, False
        w0 = inner[0]
        b0 = base(w0)
        dynamic_tool = False
        args = inner[1:]
        if DYN in w0:
            # A run-time word in command position (`$(echo cat)`, `$X`, and the
            # word-splitting `cat${IFS}x.py`): unknown means "may be a read tool".
            parts = w0.split(DYN)
            static = w0.replace(DYN, "")
            if base(parts[0]) in READ_TOOLS:
                dynamic_tool = True
                args = [p for p in parts[1:] if p] + args
            elif not static or base(static) in READ_TOOLS:
                dynamic_tool = True
        if dynamic_tool or b0 in READ_TOOLS:
            self.judge_tool(b0, args, cwds, piped_in, flags, dynamic_tool)
        elif b0 == "find":
            self.find_exec(inner, cwds)
        elif b0 in SHELLS:
            sub_state = State(cwds, {})
            has_c = has_operand = False
            for k in range(1, len(inner)):
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", inner[k]):
                    has_c = True
                    if k + 1 < len(inner):
                        if DYN in inner[k + 1] and loose(text):
                            self.emit("D", None, "shell code built at run time")
                        self.run(inner[k + 1].replace(DYN, " "), depth + 1, sub_state)
                    break
                if not inner[k].startswith(("-", "+")):
                    has_operand = True
                    break
            if not has_c and not has_operand:
                for body in rec["stdin"]:
                    self.run(body, depth + 1, sub_state)
                if piped_in and loose(text):
                    self.emit("D", None, "read piped into a shell")
        elif b0 == "eval":
            code = " ".join(inner[1:])
            if DYN in code and loose(text):
                self.emit("D", None, "eval of code built at run time")
            self.run(code.replace(DYN, " "), depth + 1, State(cwds, cur.vars))
        elif b0 in ("source", ".") and len(inner) > 1 and (inner[1] in ("/dev/stdin", "-") or DYN in inner[1]):
            if loose(text):
                self.emit("D", None, "source of generated code")
        return cur, False


try:
    if len(cmd) > 65536:
        sys.exit(3)
    a = Analyzer()
    a.run(cmd, 0, State({SESSION_CWD}, {}))
    seen = set()
    out = []
    for r in a.records:
        if r not in seen:
            seen.add(r)
            out.append("\x1f".join(r))
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))
    sys.exit(0)
except Unparseable:
    # Bash can't run it as written either, but our lexer may be the one that is
    # wrong: deny on a loose whole-text match, otherwise hand to the legacy scan.
    sys.exit(2 if loose(cmd) else 3)
except TooDeep:
    sys.exit(2)
except SystemExit:
    raise
except Exception:
    sys.exit(3)
PY

# Judge one analyzer record. CWD_REAL is set by the caller to the record's cwd.
# Each returns 0 when the read is repo source (deny).
judge_file() {
  local tok="$1" gm grc g probe rprobe is_src=0
  gm=$(glob_matches "$tok"); grc=$?
  if [[ $grc -eq 2 ]]; then
    probe=$(abs_of "$tok")
    [[ -z "$probe" ]] || in_repo "$probe"
    return
  fi
  if [[ -n "$gm" ]]; then
    while IFS= read -r g; do
      [[ -n "$g" ]] && reads_repo_source "$g" && return 0
    done <<< "$gm"
    return 1
  fi
  printf '%s' "$tok" | grep -qE "$SRC_EXT" && is_src=1
  probe=$(abs_of "$tok")
  if [[ $is_src -eq 0 && -n "$probe" ]]; then
    rprobe=$(resolve_path "$probe")
    printf '%s' "$rprobe" | grep -qE "$SRC_EXT" && in_repo "$rprobe" && is_src=1
  fi
  [[ $is_src -eq 1 ]] || return 1
  allowed_loc "$tok" && return 1
  [[ -z "$probe" ]] && return 0            # relative, cwd unknown: fail closed
  in_repo "$probe"                          # lands outside the repo → jcode can't help
}

judge_recursive() {
  local tok="$1" gm grc g probe
  allowed_loc "$tok" && return 1
  gm=$(glob_matches "$tok"); grc=$?
  if [[ $grc -eq 2 ]]; then
    probe=$(abs_of "$tok")
    [[ -z "$probe" ]] || in_repo "$probe" || is_repo_ancestor "$probe"
    return
  fi
  if [[ -n "$gm" ]]; then
    while IFS= read -r g; do
      [[ -n "$g" ]] && reads_repo_source "$g" recursive && return 0
    done <<< "$gm"
    return 1
  fi
  probe=$(abs_of "$tok")
  [[ -z "$probe" ]] && return 0
  if [[ -f "$(resolve_path "$probe")" ]]; then
    reads_repo_source "$probe" recursive
    return
  fi
  in_repo "$probe" || is_repo_ancestor "$probe"
}

judge_cwd() {
  [[ -z "$CWD_REAL" ]] && return 0
  in_repo "$CWD_REAL" || is_repo_ancestor "$CWD_REAL"
}

deny=0
USE_LEGACY=1
if command -v python3 >/dev/null 2>&1; then
  # -S: skip site.py (~10 ms of a ~15 ms start; the analyzer is stdlib-only).
  # -E: ignore PYTHON* env vars, so PYTHONPATH/PYTHONSTARTUP can't swap in code.
  RECORDS=$(printf '%s' "$CMD" | python3 -S -E -c "$GG_PROG" "$CWD_REAL" 2>/dev/null)
  prc=$?
  if [[ $prc -eq 2 ]]; then
    deny=1; USE_LEGACY=0
  elif [[ $prc -eq 0 ]]; then
    USE_LEGACY=0
    SESSION_CWD_REAL="$CWD_REAL"
    while IFS=$'\x1f' read -r r_kind r_cwd r_path; do
      [[ -z "$r_kind" ]] && continue
      CWD_REAL="$r_cwd"
      case "$r_kind" in
        D) deny=1 ;;
        F) judge_file "$r_path" && deny=1 ;;
        R) judge_recursive "$r_path" && deny=1 ;;
        C) judge_cwd && deny=1 ;;
        *) deny=1 ;;                         # unknown record: fail closed
      esac
      [[ $deny -eq 1 ]] && break
    done <<< "$RECORDS"
    CWD_REAL="$SESSION_CWD_REAL"
  fi
fi

if [[ $USE_LEGACY -eq 1 ]]; then
# ── Legacy scan: used only when the analyzer is unavailable (no python3) or could
# not lex the command. Unchanged since 2026-10-22; errs toward denying source.

# A heredoc means the command is WRITING (e.g. `cat >> audit.md <<'EOF'`) — allow outright.
echo "$CMD" | grep -qE '<<' && exit 0

# Strip a trailing shell comment so an allowed path named in a comment cannot exempt a
# real source grep (the old whole-command substring-exception bug).
CMD_CLEAN=$(printf '%s' "$CMD" | sed -E 's/[[:space:]]+#.*$//')

# Split into command segments on  &&  ||  |  ;  &  (and newlines already split rows).
SEGMENTS=$(printf '%s' "$CMD_CLEAN" | sed -E 's/(&&|\|\||;|&|\|)/\n/g')

# rg/ag/ack are recursive-by-default: a segment whose command IS one of them and that has
# no allowed-location reference reads the source tree. (When piped into — `ps | rg foo` —
# the split puts rg first-word in its own segment with no path; we still allow that because
# such a segment has neither an explicit non-allowed path nor a recursive filesystem intent
# we can confirm. Explicit `rg foo scripts/` is caught by the per-segment path scan below.)
deny=0

while IFS= read -r seg; do
  [[ -z "${seg// /}" ]] && continue

  set -f; set -- $seg; set +f
  cmd0="${1:-}"
  base="${cmd0##*/}"            # /usr/bin/grep -> grep

  case "$base" in
    grep|egrep|fgrep|cat|head|tail|sed) ;;   # rg/ag/ack handled at whole-command level below
    *) continue ;;             # this segment's command is not a read tool → ignore its args
  esac

  # sed -i / --in-place is an EDIT (write), not a read.
  if [[ "$base" == sed ]] && echo "$seg" | grep -qE 'sed[[:space:]]+(-[a-zA-Z]*i|--in-place)'; then
    continue
  fi

  # Recursive grep: an actual -r/-R flag TOKEN reads a directory tree. Flag detection is
  # per-token, not whole-segment: hyphenated words in patterns or paths ("-MORTEM",
  # "/…/-opt-proj-…/MEMORY.md", "ytd-angel-pr-pin") are NOT flags.
  if [[ "$base" == grep || "$base" == egrep || "$base" == fgrep ]]; then
    recursive=0
    set -f
    for tok in $seg; do
      case "$tok" in
        --recursive|--dereference-recursive) recursive=1; break ;;
        --*) ;;                                            # long option, not recursive
        -*[rR]*) echo "$tok" | grep -qE '^-[a-zA-Z]+$' && { recursive=1; break; } ;;
      esac
    done
    set +f
    if [[ $recursive -eq 1 ]]; then
      # Deny only when a path operand can reach the repo tree. Walk the operands:
      # skip the command, flag tokens, redirects, detached numeric flag values, and
      # the first non-flag arg (the search pattern). Absolute/~ paths OUTSIDE the
      # repo are allowed (jcode can't help there); relative paths resolve in the
      # repo cwd and no-path means cwd itself → deny both.
      # Allowed locations are judged PER OPERAND (allowed_loc). The old whole-segment
      # ALLOWED_RE test let `grep -rn foo scripts/ /tmp/` through on the /tmp/ alone.
      # Exception: every --include filter naming an allowed kind (`--include=*.log`)
      # means only those files are read, whatever the tree.
      first=1; pattern_seen=0; has_path=0; repo_path=0; inc_any=0; inc_bad=0
      set -f
      for tok in $seg; do
        if [[ $first -eq 1 ]]; then first=0; continue; fi
        case "$tok" in
          --include=*)
            inc_any=1
            printf '%s' "${tok#--include=}" | grep -qE "$ALLOWED_RE" || inc_bad=1
            continue ;;
        esac
        [[ "$tok" == -* ]] && continue
        [[ "$tok" == *">"* ]] && continue
        if [[ $pattern_seen -eq 0 ]]; then pattern_seen=1; continue; fi
        # After the pattern slot is filled, a bare numeral is a detached flag
        # value (`-A 3`), not a path. Checked after pattern_seen so a numeric
        # PATTERN (`grep -rl 500 /home/...`) can't swallow the path operand.
        echo "$tok" | grep -qE '^[0-9]+$' && continue
        has_path=1
        allowed_loc "$tok" && continue
        # A glob is judged by what it matches; past the cap, fail closed in the repo.
        gm=$(glob_matches "$tok"); grc=$?
        if [[ $grc -eq 2 ]]; then
          probe=$(abs_of "$tok")
          if [[ -z "$probe" ]] || in_repo "$probe" || is_repo_ancestor "$probe"; then repo_path=1; fi
          continue
        fi
        if [[ -n "$gm" ]]; then
          while IFS= read -r g; do
            [[ -n "$g" ]] && reads_repo_source "$g" recursive && repo_path=1
          done <<< "$gm"
          continue
        fi
        # A plain file is read alone (-r only matters for directories), so judge it
        # like a non-recursive operand: denied only when it is repo source.
        probe=$(abs_of "$tok")
        if [[ -n "$probe" && -f "$(resolve_path "$probe")" ]]; then
          reads_repo_source "$probe" recursive && repo_path=1
          continue
        fi
        case "$tok" in
          /*|"~"|"~"/*)
            probe=$(abs_of "$tok")
            if in_repo "$probe" || is_repo_ancestor "$probe"; then repo_path=1; fi ;;
          *) repo_path=1 ;;
        esac
      done
      set +f
      [[ $inc_any -eq 1 && $inc_bad -eq 0 ]] && continue
      if [[ $has_path -eq 0 || $repo_path -eq 1 ]]; then deny=1; break; fi
      continue
    fi
  fi

  # Scan THIS segment's tokens for a source file being READ. Skip the command itself,
  # flag tokens (--include=*.sh is a filter, not a file), and — for pattern-taking tools
  # (grep family, sed) — the first non-flag argument, which is the pattern/script text
  # ("ytd\.sh", 's/foo.py/bar/'), not a file operand.
  pattern_pending=0
  case "$base" in grep|egrep|fgrep|sed) pattern_pending=1 ;; esac
  set -f; prev=""; first=1
  for tok in $seg; do
    if [[ $first -eq 1 ]]; then first=0; prev="$tok"; continue; fi
    if [[ "$tok" == -* ]]; then prev="$tok"; continue; fi
    if [[ $pattern_pending -eq 1 && "$tok" != ">"* && "$prev" != ">" && "$prev" != ">>" ]]; then
      pattern_pending=0; prev="$tok"; continue
    fi
    # A glob operand reads every match: deny if any match is repo source (`cat
    # scripts/*` hid source behind an extensionless literal). Past the cap, fail
    # closed when the glob is in the repo. No match falls through to the literal rule.
    if [[ "$tok" != ">"* && "$prev" != ">" && "$prev" != ">>" ]]; then
      gm=$(glob_matches "$tok"); grc=$?
      if [[ $grc -eq 2 ]]; then
        probe=$(abs_of "$tok")
        if [[ -z "$probe" ]] || in_repo "$probe"; then deny=1; break; fi
        prev="$tok"; continue
      fi
      if [[ -n "$gm" ]]; then
        while IFS= read -r g; do
          [[ -n "$g" ]] && reads_repo_source "$g" && deny=1
        done <<< "$gm"
        [[ $deny -eq 1 ]] && break
        prev="$tok"; continue
      fi
    fi
    # A token is source when its literal spelling has a source extension, OR when it
    # resolves (symlink) into the repo onto a file that has one — `cat /tmp/notes.txt`
    # where notes.txt -> <repo>/scripts/x.py is a source read.
    is_src=0
    printf '%s' "$tok" | grep -qE "$SRC_EXT" && is_src=1
    if [[ $is_src -eq 0 && "$tok" != ">"* && "$prev" != ">" && "$prev" != ">>" ]]; then
      probe=$(abs_of "$tok")
      if [[ -n "$probe" ]]; then
        rprobe=$(resolve_path "$probe")
        printf '%s' "$rprobe" | grep -qE "$SRC_EXT" && in_repo "$rprobe" && is_src=1
      fi
    fi
    if [[ $is_src -eq 1 ]]; then
      [[ "$prev" == ">" || "$prev" == ">>" || "$tok" == ">"* ]] && { prev="$tok"; continue; }   # redirect target
      allowed_loc "$tok" && { prev="$tok"; continue; }                                            # allowed location
      # Source OUTSIDE the repo — jcode can't help there, so allow it. The guard sees the
      # RAW unexpanded command string, so a `~/…` operand never arrives as `/…`. Matching
      # only /* silently denied every home-dir source read (e.g. `grep -n foo
      # ~/.claude/hooks/discipline/grep-guard.sh`) while the identical /home/bill/…
      # spelling was allowed. Expand ~ to $HOME first, then apply the same containment
      # test to both spellings. in_repo() also resolves symlinks, so a home-dir link
      # into this repo is in-repo under either spelling. Relative operands stay denied.
      # The recursive branch above uses the same helpers — keep in sync.
      case "$tok" in
        /*|"~"|"~"/*) probe=$(abs_of "$tok")
                      ! in_repo "$probe" && { prev="$tok"; continue; } ;;                     # source outside repo
      esac
      deny=1; break
    fi
    prev="$tok"
  done
  set +f
  [[ $deny -eq 1 ]] && break
done <<< "$SEGMENTS"

# rg/ag/ack are recursive-by-default. Treat as a source search when invoked in command
# position EXCLUDING after a pipe (a piped `… | rg foo` reads stdin, not the tree) and
# with no allowed-location target.
# Operands are judged one by one with the same helpers as recursive grep: the old
# whole-command ALLOWED_RE test let `rg foo scripts/ /tmp/` and `rg foo /tmp/link`
# (link -> repo) through on the /tmp/ alone.
if [[ $deny -eq 0 ]] \
   && echo "$CMD_CLEAN" | grep -qE '(^|[;&(])[[:space:]]*(rg|ag|ack)\b'; then
  # Pipelines split on && || ; & — a single | is left inside, so stage 0 of each
  # pipeline is the command-position stage and later stages read stdin.
  PIPELINES=$(printf '%s' "$CMD_CLEAN" | sed -E 's/(&&|\|\||;|&)/\n/g')
  while IFS= read -r pl; do
    stage0="${pl%%|*}"
    stage0="${stage0#"${stage0%%[![:space:](]*}"}"     # strip leading space / (
    set -f; set -- $stage0; set +f
    case "${1##*/}" in rg|ag|ack) ;; *) continue ;; esac
    shift
    pattern_seen=0; has_path=0; repo_path=0; glob_any=0; glob_bad=0; want_val=""
    set -f
    for tok in "$@"; do
      if [[ -n "$want_val" ]]; then
        if [[ "$want_val" == glob ]]; then
          glob_any=1; printf '%s' "$tok" | grep -qE "$ALLOWED_RE" || glob_bad=1
        fi
        want_val=""; continue
      fi
      case "$tok" in
        -g|--glob|--iglob|-G) want_val=glob; continue ;;
        --glob=*|--iglob=*)
          glob_any=1; printf '%s' "${tok#*=}" | grep -qE "$ALLOWED_RE" || glob_bad=1; continue ;;
        -e|--regexp|-f|--file) pattern_seen=1; want_val=val; continue ;;   # pattern given by flag
        --regexp=*|--file=*) pattern_seen=1; continue ;;
        -t|-T|--type|--type-not|-A|-B|-C|-m|--max-count|-j|--threads|-M|--max-columns)
          want_val=val; continue ;;
        -*) continue ;;
        *">"*) continue ;;
      esac
      if [[ $pattern_seen -eq 0 ]]; then pattern_seen=1; continue; fi
      has_path=1
      allowed_loc "$tok" && continue
      case "$tok" in
        /*|"~"|"~"/*)
          probe=$(abs_of "$tok")
          if in_repo "$probe" || is_repo_ancestor "$probe"; then repo_path=1; fi ;;
        *) repo_path=1 ;;
      esac
    done
    set +f
    [[ $glob_any -eq 1 && $glob_bad -eq 0 ]] && continue
    if [[ $has_path -eq 0 || $repo_path -eq 1 ]]; then deny=1; break; fi
  done <<< "$PIPELINES"
fi
fi   # USE_LEGACY

# Tests assert WHICH path decided (a silent fall-back to the legacy scan would pass
# most cases and hide a broken analyzer).
[[ -n "${GREP_GUARD_DEBUG:-}" ]] && echo "grep-guard: path=$([[ $USE_LEGACY -eq 1 ]] && echo legacy || echo analyzer) deny=$deny" >&2

[[ $deny -eq 0 ]] && exit 0

# Collapse newlines/tabs BEFORE truncating: `head -c` cuts bytes, not lines, so a
# multi-line $CMD wrote N lines into the log and only the last carried `session=`.
# That silently broke one-entry-per-line parsing for the weekly review (385 of 3452
# lines were continuation junk). tr first, then truncate the now-single line.
log_entry "BLOCKED grep-guard cmd=$(printf '%s' "$CMD" | tr '\n\r\t' ' ' | head -c 120) session=$SESSION_ID"

REASON="Reading/searching repo source via shell is blocked — use jcodemunch (saves tokens, returns ranked structured results):

  • content/regex search  → mcp__jcodemunch__search_text(query=\"...\", repo=<repo>)
  • read a function/symbol → mcp__jcodemunch__get_symbol_source / get_context_bundle
  • read/outline a file    → mcp__jcodemunch__get_file_outline / get_file_content

Allowed without jcode: stdin pipes (… | grep), logs/state/tmp/proc targets, non-source
files, source outside this repo, and writes (redirects/heredocs/sed -i).

Find the repo id with mcp__jcodemunch__list_repos(). Logged to state/hook-blocks.log"

jq -n --arg r "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $r
  }
}'
