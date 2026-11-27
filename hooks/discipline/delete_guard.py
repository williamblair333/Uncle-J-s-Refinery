#!/usr/bin/env python3
"""Delete guard: block a Bash command that deletes data outside the repo or temp dirs.

Called by delete-guard.sh with the PreToolUse payload on stdin. Exit 2 = block,
0 = allow. Any other outcome makes the wrapper fall back to a regex, so a crash
never lets everything through.

Why (2026-11-27): a rhcsa-lab session ran `just vm-destroy rhcsa1`, which ran
`virsh undefine --remove-all-storage`. That deletes every file attached to the VM,
including the RHEL DVD ISO in its CD drive (11 GB, behind a login, no copy). Its
pre-mortem had said "the ISO is never modified" without checking. A pre-mortem is
the model judging itself; this guard is the check that holds when that judgement
is wrong.

Blocked, per command (`;` `&&` `||` `|` newline), looking through sudo/env/
timeout/nice (with their option values), shell keywords (then, do, {, !), `$(…)`,
backticks, `eval`, `bash -c` and `xargs`:
  * rm / unlink / shred of any path that isn't strictly inside /tmp, /var/tmp,
    $TMPDIR or the git work tree of the command's working directory. Never `.git`
    or a glob that could match it, never a work tree that is $HOME or /. Symlinks
    are resolved; `{a,b}` is expanded; a glob is judged by the directory it
    expands in. A path this can't resolve counts as outside; `$VAR` set earlier in
    the same command (`S=/tmp/x; rm -rf $S`, `d=$(mktemp -d)`) is resolved.
  * `xargs rm …` (its paths come from stdin, so they can't be judged).
  * find … -delete / -exec rm, judged by its start paths.
  * virsh undefine --remove-all-storage / --wipe-storage; virsh vol-delete,
    vol-wipe, pool-delete.
  * dd of=/dev/…, mkfs*, wipefs, blkdiscard.
  * git reset --hard; git clean -f (unless -n / --dry-run).
  * docker/podman volume rm|prune, system prune, compose down -v/--volumes
    (docker-compose too), except a compose project whose files are under /tmp.
  * a `just` recipe (with its dependencies), or a shell script run directly
    (bash x.sh, ./x.sh, source x.sh), whose text contains one of the
    always-destructive forms above. Comments are skipped. `just --show` prints a
    recipe without evaluating backticks. Python files and this guard's own files
    aren't scanned: their destructive strings are data.
Allowed: a command prefixed `DELETE_OK="<what it deletes; who approved>"`. The
prefix is logged. It is for after the deletion has been listed and, for anything
that can't be recreated in minutes, William has said yes.

Out of scope: a session determined to dodge the guard (base64 | sh, a Python
one-liner calling shutil.rmtree, a script written and run in two calls). The
guard is for an honest session that is wrong about what a command deletes.
Tests: tests/test_delete_guard.py.
"""
from __future__ import annotations

import fnmatch
import itertools
import json
import os
import re
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pipe_to_shell_guard import (  # noqa: E402  (same directory; -I drops it from sys.path)
    SEPARATORS, inner_scripts, split_on, strip_heredoc_bodies, tokens,
)

# Destructive forms that are never routine, matched in script and recipe text.
SCRIPT_RE = re.compile(
    r"--remove-all-storage|--wipe-storage|\bvol-(?:delete|wipe)\b|\bpool-delete\b"
    r"|\bmkfs(?:\.\w+)?\b|\bwipefs\b|\bblkdiscard\b|\bgit\s+reset\s+--hard\b"
    r"|\b(?:docker|podman)\s+(?:volume\s+(?:rm|prune)|system\s+prune)\b"
    r"|\bdd\b[^\n]*\bof=/dev/(?!null\b|stdout\b)"
)
REDIRECT = re.compile(r"[<>&|]+")
ASSIGN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.S)
DELETERS = {"rm", "unlink", "shred"}
# Words that put the real command later in the same stage. The set maps each to
# the options that take a value, so `sudo -u root rm` finds `rm`, not `root`.
WRAPPERS = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T", "--user", "--group"},
    "doas": {"-u", "-C"}, "env": {"-u", "-C", "-S", "--unset", "--chdir"},
    "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"}, "nohup": set(), "time": {"-f", "-o"},
    "command": set(), "builtin": set(), "exec": {"-a"}, "busybox": set(), "stdbuf": {"-i", "-o", "-e"},
    "setsid": set(), "watch": {"-n", "-d", "--interval"}, "chronic": set(), "unbuffer": set(),
    "then": set(), "do": set(), "else": set(), "elif": set(), "if": set(), "while": set(),
    "until": set(), "{": set(), "}": set(), "!": set(), "eval": set(),
}
OWN_FILES = {os.path.realpath(os.path.join(HERE, n)) for n in ("delete_guard.py", "delete-guard.sh")}


# ── text preparation ─────────────────────────────────────────────────────────

def strip_shell_comments(cmd: str) -> str:
    """Drop `# …` comments outside quotes. An apostrophe in a comment (`# it's`)
    would otherwise open a quote that never closes and crash the tokenizer."""
    out, i, n = [], 0, len(cmd)
    quote = None
    while i < n:
        c = cmd[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
        elif quote == '"':
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(cmd[i + 1])
                i += 1
            elif c == '"':
                quote = None
        elif c == "\\" and i + 1 < n:
            out.append(c + cmd[i + 1])
            i += 1
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;&|()"):
            while i < n and cmd[i] != "\n":
                i += 1
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def substitutions(cmd: str) -> list[str]:
    """Bodies of `$(…)` (balanced, outside single quotes) and backtick pairs."""
    found, i, quote = [], 0, None
    while i < len(cmd):
        c = cmd[i]
        if c == "'" and quote is None:
            j = cmd.find("'", i + 1)
            i = len(cmd) if j < 0 else j + 1
            continue
        if c == "$" and cmd[i + 1:i + 2] == "(" and cmd[i + 2:i + 3] != "(":
            depth, j = 1, i + 2
            while j < len(cmd) and depth:
                depth += {"(": 1, ")": -1}.get(cmd[j], 0)
                j += 1
            found.append(cmd[i + 2:j - 1])
            i = j
            continue
        if c == "`":
            j = cmd.find("`", i + 1)
            if j > 0:
                found.append(cmd[i + 1:j])
                i = j + 1
                continue
        i += 1
    return found


def strip_comments(text: str) -> str:
    """For script and recipe text: drop comment lines and trailing comments."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"(^|\s)#.*$", "", line))
    return "\n".join(out)


def clean_args(args: list[str]) -> list[str]:
    """Drop redirections (`2>/dev/null`, `> f`) and subshell parens from an arg list."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in {"(", ")"}:
            continue
        if REDIRECT.fullmatch(a):
            if out and out[-1].isdigit():
                out.pop()
            skip = True
            continue
        out.append(a)
    return out


def real_command(stage: list[str]) -> tuple[str, str, list[str], dict[str, str], str | None]:
    """(basename of the command, the word as typed, its args, VAR=value prefixes,
    a directory `env -C` runs it in)."""
    env: dict[str, str] = {}
    chdir = None
    stage = [w for w in stage if w not in {"(", ")"}]
    i = 0
    while i < len(stage):
        w = stage[i]
        m = ASSIGN.fullmatch(w)
        if m:
            env[m.group(1)] = m.group(2)
            i += 1
            continue
        base = os.path.basename(w)
        if base == "flock":  # flock [opts] FILE cmd …
            i += 1
            while i < len(stage) and stage[i].startswith("-"):
                i += 2 if stage[i] in {"-w", "--timeout", "-E", "--conflict-exit-code"} else 1
            i += 1
            continue
        if base in WRAPPERS:
            vals = WRAPPERS[base]
            i += 1
            while i < len(stage):
                a = stage[i]
                if a in vals and i + 1 < len(stage):
                    if base == "env" and a in {"-C", "--chdir"}:
                        chdir = stage[i + 1]
                    i += 2
                elif a.startswith("-") or (base == "timeout" and re.fullmatch(r"[0-9.]+[smhd]?", a)) \
                        or (base == "env" and ASSIGN.fullmatch(a)):
                    i += 1
                else:
                    break
            continue
        return base, w, clean_args(stage[i + 1:]), env, chdir
    return "", "", [], env, chdir


# ── paths ────────────────────────────────────────────────────────────────────

def git_top(path: str) -> str | None:
    p = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


VAR_REF = re.compile(r"\$\{([A-Za-z_]\w*)(?::?[-?=+][^}]*)?\}|\$([A-Za-z_]\w*)")  # ${S:?} ${S:-x} too
BRACE = re.compile(r"\{([^{}]*,[^{}]*)\}")


def expand(text: str, shvars: dict[str, str] | None) -> str:
    """Replace $VAR / ${VAR} set earlier in the same command line (`S=/tmp/x; rm -rf $S`)."""
    if not shvars:
        return text
    return VAR_REF.sub(lambda m: shvars.get(m.group(1) or m.group(2), m.group(0)), text)


def braces(target: str) -> list[str]:
    """`{a,b}/c` → [a/c, b/c]; capped so a pathological pattern can't blow up."""
    parts = BRACE.split(target)
    if len(parts) == 1:
        return [target]
    choices = [[p] if k % 2 == 0 else p.split(",") for k, p in enumerate(parts)]
    out = ["".join(c) for c in itertools.islice(itertools.product(*choices), 64)]
    return out


def resolve(target: str, cwd: str | None, shvars: dict[str, str] | None = None) -> tuple[str, str] | None:
    """(real directory-or-path, glob remainder or "") for a target, or None when it
    can't be known. A glob is judged by the directory it expands in."""
    home = os.path.expanduser("~")
    t = expand(target, {**(shvars or {}), "HOME": home})
    if t == "~" or t.startswith("~/"):
        t = home + t[1:]
    if "`" in t or "$(" in t or t.startswith(("~", "$")) or not t:
        return None
    # An unknown $var inside a path (`/tmp/$f.txt`) is judged like a glob: by the
    # directory it sits in. One at the start (`$X/y`) can't be judged at all.
    g = re.search(r"[*?\[$]", t)
    rest = ""
    if g:
        cut = t.rfind("/", 0, g.start())
        base, rest = (t[:cut] or "/", t[cut + 1:]) if cut >= 0 else (".", t)
        t = base
        if ".." in rest.split("/"):
            return None  # `*/../../x` can climb anywhere
    if not os.path.isabs(t):
        if cwd is None:
            return None
        t = os.path.join(cwd, t)
    return os.path.realpath(os.path.normpath(t)), rest


def safe_roots(cwd: str | None) -> list[str]:
    home = os.path.realpath(os.path.expanduser("~"))
    roots = [os.path.realpath("/tmp"), os.path.realpath("/var/tmp")]
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir and os.path.realpath(tmpdir) not in {"/", home}:
        roots.append(os.path.realpath(tmpdir))
    if cwd:
        top = git_top(cwd)
        if top and top not in {"/", home}:
            roots.append(top)
    return roots


def path_ok(target: str, cwd: str | None, shvars: dict[str, str] | None = None) -> bool:
    for t in braces(target):
        r = resolve(t, cwd, shvars)
        if r is None:
            return False
        p, rest = r
        if ".git" in p.split("/"):
            return False
        comp = rest.split("/")[0]
        if comp.startswith((".", "[")) and fnmatch.fnmatch(".git", comp):
            return False  # `.*`, `.git*`, `.[a-z]*` match .git (bash's `*` skips dotfiles)
        if comp.startswith("$") and os.path.exists(os.path.join(p, ".git")):
            return False  # `$x` beside a .git could be .git
        if "$" in rest and ".." in rest:
            return False
        ok = False
        for root in safe_roots(cwd):
            if p.startswith(root + "/"):
                ok = True
            elif rest and p == root and (root not in {"/tmp", "/var/tmp"}
                                         or re.sub(r"[*?/]|\$\{?\w+\}?", "", rest)):
                ok = True  # `rm -rf *` at the work tree's top stays inside it; in /tmp only
                # a pattern with a literal part (`/tmp/$f.txt`, not `/tmp/*`)
        if not ok:
            return False
    return True


def operands(args: list[str]) -> list[str]:
    out, done = [], False
    for a in args:
        if done or not a.startswith("-") or a == "-":
            out.append(a)
        elif a == "--":
            done = True
    return out


def subcommand(args: list[str], takes_value: set[str]) -> tuple[str, list[str]]:
    i = 0
    while i < len(args):
        a = args[i]
        if a in takes_value:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return "", []


# ── scripts and just recipes ─────────────────────────────────────────────────

SHELL_VALUE_OPTS = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}


def script_paths(word: str, typed: str, args: list[str], cwd: str | None,
                 shvars: dict[str, str] | None) -> list[str]:
    """Shell script files this command runs: `bash x.sh`, `./x.sh`, `source x.sh`."""
    cand = []
    if word in {"bash", "sh", "zsh", "dash", "ksh"}:
        if not any(re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", a) for a in args):
            i = 0
            while i < len(args):
                if args[i] in SHELL_VALUE_OPTS:
                    i += 2
                    continue
                if not args[i].startswith(("-", "+")):
                    cand.append(args[i])
                    break
                i += 1
    elif word in {"source", "."} and args:
        cand.append(args[0])
    elif "/" in typed:
        cand.append(typed)
    out = []
    for c in cand:
        r = resolve(c, cwd, shvars)
        if r and not r[1] and os.path.isfile(r[0]) and is_shell_file(r[0]):
            out.append(r[0])
    return out


def is_shell_file(path: str) -> bool:
    if os.path.realpath(path) in OWN_FILES:
        return False
    if path.endswith((".sh", ".bash")):
        return True
    if path.endswith((".py", ".rb", ".pl", ".js", ".ts")):
        return False
    try:
        with open(path, "rb") as fh:
            first = fh.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and re.search(rb"\b(ba|z|da|k)?sh\b", first) is not None


def read_text(path: str, limit: int = 2_000_000) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit)
    except OSError:
        return ""
    if b"\0" in data[:4096]:
        return ""
    return data.decode("utf-8", "replace")


def scan_text(text: str) -> str | None:
    m = SCRIPT_RE.search(strip_comments(text))
    return m.group(0) if m else None


JUST_INFO = {"-l", "--list", "-s", "--show", "--summary", "--evaluate", "-h", "--help", "-V",
             "--version", "--dump", "--variables", "--fmt", "--init", "--edit", "-e",
             "--completions", "--groups", "--changelog", "--man", "--check"}
JUST_VALUE = {"-f", "--justfile", "-d", "--working-directory", "--shell", "--shell-arg",
              "--dotenv-filename", "--dotenv-path", "-E", "--color", "--command-color",
              "--list-heading", "--list-prefix", "--chooser", "--timestamp-format", "--unstable",
              "--command", "-c"}


def run_just(opts: list[str], extra: list[str], cwd: str | None) -> str | None:
    try:
        r = subprocess.run(["just", *opts, *extra], cwd=cwd or None, capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def recipe_deps(body: str) -> list[str]:
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "[", "@[")):
            continue
        s = re.sub(r"'[^']*'|\"[^\"]*\"", "", s)
        m = re.match(r"@?[\w-]+[^:]*:(?!=)(.*)$", s)
        if not m:
            return []
        deps = re.sub(r"\(([\w-]+)[^)]*\)", r"\1", m.group(1)).replace("&&", " ")
        return re.findall(r"[A-Za-z_][\w-]*", deps)
    return []


def just_recipes(args: list[str], cwd: str | None) -> tuple[list[str], str] | None:
    """(bodies of the recipe it runs and its dependencies, directory paths resolve
    against), or None when nothing runs or just can't answer."""
    opts: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        key = a.split("=", 1)[0]
        if key in JUST_INFO:
            return None
        if a == "--set" and i + 2 < len(args):
            i += 3
            continue
        if key in JUST_VALUE:
            if "=" in a:
                opts += [key, a.split("=", 1)[1]]
                i += 1
            elif i + 1 < len(args):
                opts += [a, args[i + 1]]
                i += 2
            else:
                i += 1
            continue
        if a.startswith("-"):
            i += 1
            continue
        if ASSIGN.fullmatch(a):  # variable override: `just foo=1 recipe`
            i += 1
            continue
        break
    opts = [o for k, o in enumerate(opts) if not (opts[k - 1] if k else "") in {"--command", "-c"}
            and o not in {"--command", "-c"}]
    if i < len(args):
        first = args[i]
    else:
        listing = run_just(opts, ["--summary", "--unsorted"], cwd)
        if not listing or not listing.split():
            return None
        first = listing.split()[0]
    bodies, todo, seen = [], [first], set()
    while todo and len(seen) < 20:
        name = todo.pop(0)
        if name in seen:
            continue
        seen.add(name)
        body = run_just(opts, ["--show", name], cwd)
        if body is None:
            continue
        bodies.append(body)
        todo += recipe_deps(body)
    if not bodies:
        return None
    base = cwd or "."
    for k, a in enumerate(opts):
        if a in {"-f", "--justfile"}:
            r = resolve(opts[k + 1], cwd)
            base = os.path.dirname(r[0]) if r else base
        elif a in {"-d", "--working-directory"}:
            r = resolve(opts[k + 1], cwd)
            base = r[0] if r else base
    if not any(a in {"-f", "--justfile"} for a in opts) and cwd:
        top = cwd  # just walks up to find the justfile; recipes run in its directory
        while not any(os.path.isfile(os.path.join(top, n)) for n in ("justfile", "Justfile", ".justfile")):
            parent = os.path.dirname(top)
            if parent == top:
                top = cwd
                break
            top = parent
        base = top
    return bodies, base


SCRIPT_CALL = re.compile(
    r"(?:\b(?:bash|sh|source)\s+(?:[-+]\w+\s+(?:\w+\s+)?)*|(?<![\w/.])\./|^\s*\.\s+)([\w./-]+)", re.M)


def judge_recipe(bodies: list[str], base: str) -> str | None:
    for body in bodies:
        hit = scan_text(body)
        if hit:
            return hit
        for s in SCRIPT_CALL.findall(strip_comments(body)):
            p = s if os.path.isabs(s) else os.path.join(base, s)
            if os.path.isfile(p) and is_shell_file(p):
                hit = scan_text(read_text(p))
                if hit:
                    return f"{hit} (in {os.path.relpath(p, base)})"
    return None


# ── judging ──────────────────────────────────────────────────────────────────

def judge(word: str, typed: str, args: list[str], cwd: str | None,
          shvars: dict[str, str] | None = None) -> str | None:
    """Reason to block one command, or None."""
    if any(a in {"--help", "-h"} for a in args) and word not in DELETERS:
        return None  # `docker volume prune --help` deletes nothing
    if word == "docker-compose":
        word, args = "docker", ["compose", *args]
    if word in DELETERS:
        bad = [a for a in operands(args) if not path_ok(a, cwd, shvars)]
        if bad:
            return f"{word} outside the repo and temp dirs: {' '.join(bad[:3])}"
    elif word == "xargs":
        k = 0
        while k < len(args) and args[k].startswith("-"):
            k += 2 if args[k] in {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "-i"} else 1
        if k < len(args) and os.path.basename(args[k]) in DELETERS:
            return f"xargs {os.path.basename(args[k])}: the paths come from stdin and can't be checked"
    elif word == "find":
        deletes = "-delete" in args or any(
            a in {"-exec", "-execdir", "-ok", "-okdir"} and k + 1 < len(args)
            and os.path.basename(args[k + 1]) in DELETERS
            for k, a in enumerate(args))
        if deletes:
            k = 0
            while k < len(args) and (args[k] in {"-H", "-L", "-P"} or re.fullmatch(r"-O\d*", args[k])
                                     or args[k] == "-D"):
                k += 2 if args[k] == "-D" else 1
            starts = []
            for a in args[k:]:
                if a.startswith("-") or a in {"!", "(", ")"}:
                    break
                starts.append(a)
            bad = [a for a in (starts or ["."]) if not path_ok(a.rstrip("/") + "/x", cwd, shvars)]
            if bad:
                return f"find … -delete outside the repo and temp dirs: {' '.join(bad[:3])}"
    elif word == "virsh":
        sub, rest = subcommand(args, {"-c", "--connect", "-r", "-l", "--log", "-k", "-K"})
        if sub == "undefine":
            hit = [a for a in rest if a in {"--remove-all-storage", "--wipe-storage"}]
            if hit:
                return (f"virsh undefine {hit[0]} deletes EVERY file attached to the domain, "
                        "CD/DVD ISOs included; name the disks instead: --storage vda,vdb")
        elif sub in {"vol-delete", "vol-wipe", "pool-delete"}:
            return f"virsh {sub}"
    elif word == "dd":
        if any(a.startswith("of=/dev/") and a not in {"of=/dev/null", "of=/dev/stdout"} for a in args):
            return "dd onto a device"
    elif word.startswith("mkfs") or word in {"wipefs", "blkdiscard"}:
        return word
    elif word == "sgdisk" and any(a.startswith(("--zap", "-Z", "-z")) for a in args):
        return "sgdisk --zap"
    elif word == "git":
        sub, rest = subcommand(args, {"-C", "-c", "--git-dir", "--work-tree"})
        if sub == "reset" and "--hard" in rest:
            return "git reset --hard (drops uncommitted work)"
        if sub in {"checkout", "switch"} and ({"-f", "--force", "--discard-changes"} & set(rest)):
            return f"git {sub} --force (drops uncommitted work)"
        if sub == "stash" and rest[:1] == ["clear"]:
            return "git stash clear"
        # `git worktree remove --force` is NOT blocked: the 30-day replay (2026-11-27) found
        # it 63 times, all routine cleanup after a merge, which would bury the real blocks.
        if sub == "clean":
            flags = "".join(a.lstrip("-") for a in rest if re.fullmatch(r"-[a-zA-Z]+", a))
            if ("f" in flags or "--force" in rest) and "n" not in flags and "--dry-run" not in rest:
                extra = " and ignored" if "x" in flags.lower() else ""
                return f"git clean -f (deletes untracked{extra} files)"
    elif word in {"docker", "podman"}:
        sub, rest = subcommand(args, {"-H", "--host", "--context", "-c", "--config", "--log-level"})
        nxt = next((a for a in rest if not a.startswith("-")), "")
        if sub == "volume" and nxt in {"rm", "remove", "prune"}:
            return f"{word} volume {nxt}"
        if sub == "system" and nxt == "prune":
            return f"{word} system prune"
        if sub == "compose":
            verb = next((a for k, a in enumerate(rest) if not a.startswith("-") and (
                k == 0 or rest[k - 1] not in {"-f", "--file", "-p", "--project-name", "--project-directory",
                                              "--env-file", "--profile", "--ansi", "--progress"})), "")
            after = rest[rest.index(verb) + 1:] if verb else []
            vflag = any(a == "--volumes" or re.fullmatch(r"-[a-zA-Z]*v[a-zA-Z]*", a) for a in after)
            if verb in {"down", "rm"} and vflag:
                where = [rest[k + 1] for k, a in enumerate(rest[:-1])
                         if a in {"-f", "--file", "--project-directory"}]
                tmp = [os.path.realpath(t) for t in ("/tmp", "/var/tmp")]
                inside = []
                for w_ in where:
                    r_ = resolve(w_, cwd, shvars)
                    inside.append(bool(r_) and any(r_[0].startswith(t + "/") for t in tmp))
                if not where or not all(inside):
                    return f"{word} compose {verb} --volumes"  # only scratch projects under /tmp pass
    elif word == "just":
        rec = just_recipes(args, cwd)
        if rec:
            hit = judge_recipe(*rec)
            if hit:
                return f"the just recipe runs {hit}"
    for p in script_paths(word, typed, args, cwd, shvars):
        hit = scan_text(read_text(p))
        if hit:
            return f"script {os.path.basename(p)} runs {hit}"
    return None


MKTEMP = re.compile(r"\b([A-Za-z_]\w*)=[\"']?\$\(\s*mktemp\b([^)]*)\)")


def verdict(cmd: str, cwd: str | None, depth: int = 0,
            shvars: dict[str, str] | None = None) -> tuple[str | None, list[str]]:
    """(reason to block or None, DELETE_OK reasons that allowed something)."""
    oks: list[str] = []
    shvars = dict(shvars or {})
    cmd = strip_shell_comments(strip_heredoc_bodies(cmd))
    # `d=$(mktemp -d)` makes a fresh temp path; `-p DIR` puts it under DIR
    temps = {m.group(1): m.group(2) for m in MKTEMP.finditer(cmd)}
    if depth < 3:  # `echo $(rm -rf ~/x)`, backticks
        for sub in substitutions(cmd):
            if not re.match(r"\s*mktemp\b", sub):
                r, more = verdict(sub, cwd, depth + 1, shvars)
                oks += more
                if r:
                    return f"{r}, inside $(…)", oks
    for command in split_on(tokens(cmd), SEPARATORS):
        for stage in split_on(command, {"|", "|&"}):
            word, typed, args, env, chdir = real_command(stage)
            ok = env.get("DELETE_OK", "").strip()
            here = resolve(chdir, cwd, shvars)[0] if chdir and resolve(chdir, cwd, shvars) else (
                None if chdir else cwd)
            for k in [k for k in env if k in temps]:
                m = re.search(r"(?:-p|--tmpdir(?:=|\s))\s*(\S+)", temps[k])
                base = resolve(m.group(1).strip("\"'"), cwd, shvars) if m else ("/tmp", "")
                shvars[k] = (base[0] if base else "$UNKNOWN") + "/mktemp.X"
            if word == "mktemp" or (not word and env):
                for k, v in env.items():  # a bare `S=/tmp/x`: later $S means that path
                    if k in temps:
                        continue
                    if "$(" in v or "`" in v or v in {"$", ""}:
                        shvars.pop(k, None)
                    else:
                        shvars[k] = expand(v, shvars)
                continue
            if word in {"cd", "pushd"}:
                dest = args[0] if args else "~"
                r = None if dest == "-" else resolve(dest, cwd, shvars)
                cwd = r[0] if r and not r[1] else None
                continue
            if word == "popd":
                cwd = None
                continue
            reasons = []
            if ")" in stage[1:] and depth < 3:  # `case x in x) rm …;;`: judge what follows `)`
                tail = stage[len(stage) - stage[::-1].index(")"):]
                if tail:
                    r, more = verdict(" ".join(shlex.quote(t) for t in tail), here, depth + 1, shvars)
                    oks += more
                    if r:
                        reasons.append(r)
            if word in {"bash", "sh", "zsh", "dash", "ksh"} and "<" in stage:
                k = stage.index("<")  # `sh < x.sh` runs x.sh
                for p_ in script_paths("bash", typed, stage[k + 1:k + 2], here, shvars):
                    hit = scan_text(read_text(p_))
                    if hit:
                        reasons.append(f"script {os.path.basename(p_)} runs {hit}")
            if depth < 3:
                scripts = list(inner_scripts(stage))
                if word == "su" and "-c" in args and args.index("-c") + 1 < len(args):
                    scripts.append(args[args.index("-c") + 1])
                if os.path.basename(stage[0]) == "eval" if stage else False:
                    scripts.append(" ".join(args if not typed else [typed, *args]))
                for script in scripts:
                    r, more = verdict(script, here, depth + 1, shvars)
                    oks += more
                    if r:
                        reasons.append(f"{r}, inside a -c script")
            r = judge(word, typed, args, here, shvars)
            if r:
                reasons.append(r)
            for r in reasons:
                if not ok:
                    return r, oks
                oks.append(f"{ok} [{r}]")
    return None, oks


FALLBACK = re.compile(
    SCRIPT_RE.pattern
    + r"|\b(?:rm|unlink|shred)\s+(?:-\w+\s+)*[\"']?(?:/(?!tmp/)|~|\$HOME|\.\.)"
    + r"|\bgit\s+(?:-C\s+\S+\s+)?clean\s+-\w*f|\bcompose\s+down\b[^\n]*\s(?:-v|--volumes)\b"
    + r"|\bfind\b[^\n]*\s-delete\b|\bxargs\b[^\n|;&]*\b(?:rm|shred|unlink)\b"
)

HOW = ("Before retrying: (1) list exactly what it will delete (ls -la, virsh domblklist --details, "
       "git status --ignored, docker volume ls); (2) if any of it can't be recreated in minutes, "
       "ask William and wait for a yes; (3) rerun with the command prefixed "
       "DELETE_OK=\"<what gets deleted; who approved>\". The prefix is logged.")


def main() -> int:
    raw = sys.stdin.read()
    cwd = None
    try:
        payload = json.loads(raw)
        cmd = payload.get("tool_input", {}).get("command") or ""
        cwd = payload.get("cwd") or None
    except (ValueError, AttributeError):
        cmd = raw
    cwd = cwd or os.getcwd()
    if not cmd.strip():
        return 0
    try:
        reason, oks = verdict(cmd, cwd)
    except Exception:  # unparseable (unbalanced quotes …): judge by the regex
        m = FALLBACK.search(strip_heredoc_bodies(cmd))
        reason, oks = (f"{m.group(0)} (regex fallback)" if m else None), []
        if reason and re.search(r"(^|[\s;&|(])DELETE_OK=\S", cmd):
            oks, reason = [f"DELETE_OK (regex fallback) [{reason}]"], None
    for ok in oks:
        print(f"DELETE_OK {ok}")
    if reason:
        print(f"BLOCKED (delete-guard): {reason}. {HOW}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
