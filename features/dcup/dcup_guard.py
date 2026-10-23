#!/usr/bin/env python3
"""dcup-guard: PreToolUse hook that keeps Claude Code's Bash calls on the port registry.

Blocks commands that would claim a fixed host port without going through `dcup`:

  * `docker compose up|create` (and `docker-compose`, `docker container ...`, `dcup --bypass`)
  * `docker compose run --service-ports | -p/--publish`
  * `docker run|create` (and `docker container run|create`) publishing a FIXED host port
    (`-p 8080:80`, `-p 127.0.0.1:8080:80`, `--publish=...`). `-p 80` and `-P` pick a random
    host port, so they claim nothing and stay allowed.

Everything else passes: `docker ps`, `docker compose logs|ps|config|down|pull`, `dcup up`, text
that only *mentions* the commands (quoted arguments, heredoc bodies fed to non-shells, comments).

The command is tokenized like a shell would (quotes, escapes, `;` `&&` `||` `|` `&`, newlines,
`$(...)`, backticks, heredocs), then each simple command is unwrapped: env assignments, `sudo`,
`env`, `nohup`, `timeout`, `nice`, `xargs`, `exec`, `command`, ...; `bash -c` / `sh -c` / `eval` /
`su -c` / `flock -c` / `env -S` strings are analyzed recursively, as are heredocs and pipes fed
into a shell's stdin. Not covered (static analysis cannot see them): commands run from inside a
script file, and names built at runtime (`D=docker; $D run -p ...` with no visible `compose`).

Exit 0 = allow, exit 2 = block (reason on stderr, which Claude sees). An internal error allows
the command and says so on stderr: a guard bug must not take Bash away from every session.

Kill switch: DCUP_GUARD=off in the hook's environment (the `env` block of
~/.claude/settings.json). A `DCUP_GUARD=off docker ...` prefix inside the command does nothing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

MAX_DEPTH = 8

ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "mksh", "ash", "busybox"}
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "(", ")",
            "nohup", "setsid", "builtin", "unbuffer", "chronic", "catchsegv"}

# docker CLI global options that take a value (separate token form).
DOCKER_GLOBAL_VALUE = {"-H", "--host", "-c", "--context", "--config", "-l", "--log-level",
                       "--tlscacert", "--tlscert", "--tlskey"}
COMPOSE_GLOBAL_VALUE = {"-f", "--file", "-p", "--project-name", "--project-directory",
                        "--env-file", "--profile", "--ansi", "--parallel", "--progress"}
# docker run/create options that take NO value. Every other option takes one.
RUN_BOOL_SHORT = set("dtiPq")
RUN_BOOL_LONG = {"--detach", "--interactive", "--tty", "--rm", "--privileged", "--publish-all",
                 "--init", "--read-only", "--sig-proxy", "--no-healthcheck", "--oom-kill-disable",
                 "--disable-content-trust", "--quiet", "--help", "--use-api-socket"}

UP_MSG = ("`{cmd}` starts containers without the port registry. Use `dcup up` with the same "
          "flags (e.g. `dcup -f compose.yaml up -d`): it checks conflicts, then claims the ports.")
RUN_MSG = ("`docker {sub}` publishes fixed host port `{spec}` outside the port registry. Put the "
           "service in a compose file and start it with `dcup up`, or publish no fixed host port "
           "(`-p CONTAINER_PORT` or `-P` pick a free one).")


# ── tokenizer ─────────────────────────────────────────────────────────────────

class Cmd:
    __slots__ = ("words", "stdin_texts", "piped_from")

    def __init__(self) -> None:
        self.words: list[str] = []
        self.stdin_texts: list[str] = []   # heredoc / here-string bodies
        self.piped_from: Cmd | None = None


def _find_closing_paren(s: str, i: int) -> int:
    """s[i] is just past '$(' / '<(' — return index of the matching ')' (or len(s))."""
    depth, n = 1, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            i += 1
            while i < n and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n


def _find_backtick(s: str, i: int) -> int:
    n = len(s)
    while i < n:
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "`":
            return i
        i += 1
    return n


def _substitutions(text: str) -> list[str]:
    """Bodies of $(...) and `...` in text that a shell would expand (heredoc bodies)."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text.startswith("$(", i):
            end = _find_closing_paren(text, i + 2)
            out.append(text[i + 2:end])
            i = end + 1
            continue
        if text[i] == "`":
            end = _find_backtick(text, i + 1)
            out.append(text[i + 1:end])
            i = end + 1
            continue
        i += 1
    return out


def parse(script: str) -> tuple[list[Cmd], list[str]]:
    """Split a shell string into simple commands. Returns (commands, nested_scripts) where
    nested_scripts are command/process substitution bodies to analyze on their own."""
    cmds: list[Cmd] = []
    nested: list[str] = []
    cur = Cmd()
    word: list[str] = []
    in_word = False
    pending: list[tuple[str, bool, bool, Cmd]] = []   # (delim, strip_tabs, expands, owner)
    pipe_next = False
    i, n = 0, len(script)

    def end_word() -> None:
        nonlocal word, in_word
        if in_word:
            cur.words.append("".join(word))
        word, in_word = [], False

    def end_cmd(piped: bool = False) -> None:
        nonlocal cur, pipe_next
        end_word()
        if cur.words or cur.stdin_texts:
            if pipe_next and cmds:
                cur.piped_from = cmds[-1]
            cmds.append(cur)
        cur = Cmd()
        pipe_next = piped

    def read_heredocs(pos: int) -> int:
        """pos is just past a newline; consume pending heredoc bodies."""
        for delim, strip_tabs, expands, owner in pending:
            body = []
            while pos < n:
                nl = script.find("\n", pos)
                line = script[pos:] if nl < 0 else script[pos:nl]
                pos = n if nl < 0 else nl + 1
                check = line.lstrip("\t") if strip_tabs else line
                if check == delim:
                    break
                body.append(line)
            text = "\n".join(body)
            owner.stdin_texts.append(text)
            if expands:
                nested.extend(_substitutions(text))
        pending.clear()
        return pos

    while i < n:
        c = script[i]
        if c == "\\":
            if i + 1 < n and script[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                word.append(script[i + 1])
            in_word = True
            i += 2
            continue
        if c == "'":
            j = script.find("'", i + 1)
            j = n if j < 0 else j
            word.append(script[i + 1:j])
            in_word = True
            i = j + 1
            continue
        if c == '"':
            i += 1
            while i < n and script[i] != '"':
                ch = script[i]
                if ch == "\\" and i + 1 < n and script[i + 1] in '"\\$`\n':
                    if script[i + 1] != "\n":
                        word.append(script[i + 1])
                    i += 2
                    continue
                if script.startswith("$(", i):
                    end = _find_closing_paren(script, i + 2)
                    nested.append(script[i + 2:end])
                    word.append("$(...)")
                    i = end + 1
                    continue
                if ch == "`":
                    end = _find_backtick(script, i + 1)
                    nested.append(script[i + 1:end])
                    word.append("`...`")
                    i = end + 1
                    continue
                word.append(ch)
                i += 1
            in_word = True
            i += 1
            continue
        if script.startswith("$(", i) or (script.startswith("<(", i) or script.startswith(">(", i)):
            end = _find_closing_paren(script, i + 2)
            nested.append(script[i + 2:end])
            word.append("$(...)")
            in_word = True
            i = end + 1
            continue
        if c == "`":
            end = _find_backtick(script, i + 1)
            nested.append(script[i + 1:end])
            word.append("`...`")
            in_word = True
            i = end + 1
            continue
        if c == "#" and not in_word:
            nl = script.find("\n", i)
            i = n if nl < 0 else nl
            continue
        if c == "\n":
            end_cmd()
            i += 1
            if pending:
                i = read_heredocs(i)
            continue
        if c in " \t":
            end_word()
            i += 1
            continue
        if script.startswith("<<<", i):
            end_word()
            i += 3
            while i < n and script[i] in " \t":
                i += 1
            # Read the here-string word with the normal rules, then move it to stdin.
            before = len(cur.words)
            sub_cmds, sub_nested = parse(_take_word(script, i))
            nested.extend(sub_nested)
            text = " ".join(w for sc in sub_cmds for w in sc.words)
            cur.stdin_texts.append(text)
            i = _skip_word(script, i)
            del cur.words[before:]
            continue
        if script.startswith("<<", i):
            end_word()
            i += 2
            strip_tabs = i < n and script[i] == "-"
            if strip_tabs:
                i += 1
            while i < n and script[i] in " \t":
                i += 1
            raw = _take_word(script, i)
            i = _skip_word(script, i)
            expands = not any(q in raw for q in "'\"\\")
            delim = raw.replace("'", "").replace('"', "").replace("\\", "")
            pending.append((delim, strip_tabs, expands, cur))
            continue
        if script.startswith("&&", i) or script.startswith("||", i) or script.startswith(";;", i):
            end_cmd()
            i += 2
            continue
        if script.startswith("|&", i):
            end_cmd(piped=True)
            i += 2
            continue
        if c == "|":
            end_cmd(piped=True)
            i += 1
            continue
        if c in ";&()":
            # `&>` / `>&` redirections are not separators.
            if c == "&" and (script.startswith("&>", i) or (i > 0 and script[i - 1] in "<>")):
                word.append(c)
                in_word = True
                i += 1
                continue
            end_cmd()
            i += 1
            continue
        if c in "<>":
            # Redirection: drop the operator and its target word.
            end_word()
            while i < n and script[i] in "<>&|0123456789":
                i += 1
            while i < n and script[i] in " \t":
                i += 1
            i = _skip_word(script, i)
            continue
        word.append(c)
        in_word = True
        i += 1
    end_cmd()
    return cmds, nested


def _skip_word(s: str, i: int) -> int:
    """Index just past the shell word starting at i (quotes respected)."""
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            i += 1
            while i < n and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
            continue
        if c in " \t\n;&|()<>":
            return i
        i += 1
    return n


def _take_word(s: str, i: int) -> str:
    return s[i:_skip_word(s, i)]


# ── command analysis ──────────────────────────────────────────────────────────

def _base(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _skip_opts(words: list[str], value_opts: set[str]) -> list[str]:
    """Drop leading options (and the values of value_opts) and a `--` terminator."""
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--":
            return words[i + 1:]
        if not w.startswith("-") or w == "-":
            return words[i:]
        i += 2 if w in value_opts else 1
    return []


def unwrap(words: list[str]) -> tuple[list[str], list[str], bool, bool]:
    """Strip assignments and wrappers. Returns (words, scripts, via_xargs, stdin_shell).

    scripts: strings a wrapper will execute as shell code (bash -c, eval, su -c, ...).
    stdin_shell: the command is a shell reading its program from stdin.
    """
    scripts: list[str] = []
    via_xargs = False
    while words:
        w = words[0]
        if ASSIGN_RE.match(w):
            words = words[1:]
            continue
        b = _base(w)
        rest = words[1:]
        if b in KEYWORDS:
            words = rest
        elif b == "time":
            words = _skip_opts(rest, set())
        elif b == "exec":
            words = _skip_opts(rest, {"-a"})
        elif b == "command":
            if rest and rest[0].startswith("-") and any(f in rest[0] for f in "vV"):
                return [], scripts, via_xargs, False      # lookup only, runs nothing
            words = _skip_opts(rest, set())
        elif b in ("sudo", "doas"):
            words = _skip_opts(rest, {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T"})
        elif b == "env":
            out, i = [], 0
            while i < len(rest):
                a = rest[i]
                if a in ("-S", "--split-string"):
                    if i + 1 < len(rest):
                        scripts.append(" ".join(rest[i + 1:]))
                    return [], scripts, via_xargs, False
                if a.startswith("--split-string="):
                    scripts.append(a.split("=", 1)[1] + " " + " ".join(rest[i + 1:]))
                    return [], scripts, via_xargs, False
                if a in ("-u", "--unset", "-C", "--chdir"):
                    i += 2
                    continue
                if a.startswith("-") or ASSIGN_RE.match(a):
                    i += 1
                    continue
                out = rest[i:]
                break
            words = out
        elif b in ("nice", "ionice", "chrt", "taskset", "stdbuf", "watch", "cgexec", "systemd-run"):
            value = {"nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p"},
                     "stdbuf": {"-i", "-o", "-e"}, "watch": {"-n", "--interval"},
                     "cgexec": {"-g"}, "systemd-run": {"-p", "--property", "-u", "--unit"},
                     "chrt": set(), "taskset": set()}[b]
            words = _skip_opts(rest, value)
            if b in ("chrt", "taskset") and words:
                words = words[1:]                         # priority / cpu mask
        elif b == "timeout":
            words = _skip_opts(rest, {"-s", "--signal", "-k", "--kill-after"})
            words = words[1:]                             # DURATION
        elif b == "flock":
            i = 0
            while i < len(rest):
                a = rest[i]
                if a in ("-c", "--command"):
                    if i + 1 < len(rest):
                        scripts.append(rest[i + 1])
                    return [], scripts, via_xargs, False
                if a in ("-w", "--wait", "--timeout", "-E", "--conflict-exit-code"):
                    i += 2
                    continue
                if a.startswith("-"):
                    i += 1
                    continue
                break
            words = rest[i + 1:]                          # drop the lock file
        elif b == "xargs":
            via_xargs = True
            words = _skip_opts(rest, {"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a",
                                      "--max-args", "--max-procs", "--delimiter", "--arg-file"})
        elif b in ("su", "runuser"):
            i = 0
            while i < len(rest):
                a = rest[i]
                if a in ("-c", "--command"):
                    if i + 1 < len(rest):
                        scripts.append(rest[i + 1])
                    return [], scripts, via_xargs, False
                if a.startswith("--command="):
                    scripts.append(a.split("=", 1)[1])
                    return [], scripts, via_xargs, False
                if a == "--":
                    words = rest[i + 1:]
                    break
                i += 2 if a in ("-u", "-g", "-G", "-s", "--shell", "--user") else 1
            else:
                words = []
            if b == "su":
                return [], scripts, via_xargs, False
        elif b == "eval":
            scripts.append(" ".join(rest))
            return [], scripts, via_xargs, False
        elif b in SHELLS:
            if b == "busybox":
                words = rest
                continue
            i, has_c = 0, False
            while i < len(rest):
                a = rest[i]
                if a == "--":
                    i += 1
                    break
                if a.startswith("--"):
                    i += 1
                    continue
                if a.startswith("-") or a.startswith("+"):
                    if "c" in a[1:]:
                        has_c = True
                    i += 2 if a in ("-o", "+o", "-O", "+O") else 1
                    continue
                break
            positional = rest[i:]
            if has_c:
                if positional:
                    scripts.append(positional[0])
                return [], scripts, via_xargs, False
            return [], scripts, via_xargs, not positional   # no file arg: reads stdin
        else:
            break
    return words, scripts, via_xargs, False


def fixed_host_port(spec: str) -> bool:
    """True when a -p/--publish value pins a host port ([ip:]host:container[/proto])."""
    spec = spec.strip()
    if spec.startswith("="):
        spec = spec[1:]
    if not spec:
        return False
    if any(k in spec for k in ("published=", "target=", "mode=")):   # long syntax
        m = re.search(r"published=([^,]*)", spec)
        return bool(m and m.group(1).strip())
    spec = spec.split("/", 1)[0]
    if spec.startswith("["):                       # [ipv6]:host:container
        close = spec.find("]")
        spec = spec[close + 1:].lstrip(":") if close >= 0 else spec
        parts = spec.split(":")
        return len(parts) >= 2 and parts[0] != ""
    parts = spec.split(":")
    if len(parts) == 1:
        return False                               # container port only: random host port
    host = parts[-2]
    return host != ""


def check_run(sub: str, args: list[str]) -> str | None:
    """docker run/create: block on a fixed host-port publish before the image name."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return None
        if not a.startswith("-") or a == "-":
            return None                            # image reached; the rest is the container's
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if name == "--publish":
                spec = val if eq else (args[i + 1] if i + 1 < len(args) else "")
                if fixed_host_port(spec):
                    return RUN_MSG.format(sub=sub, spec=spec)
                i += 1 if eq else 2
                continue
            # A value never starts with '-': if the next token is an option, this one was a
            # boolean missing from RUN_BOOL_LONG — don't let it swallow a following `-p`.
            takes_next = not eq and name not in RUN_BOOL_LONG and i + 1 < len(args) \
                and not args[i + 1].startswith("-")
            i += 2 if takes_next else 1
            continue
        # short option cluster, e.g. -d, -it, -dp 80:80, -p8080:80
        j = 1
        consumed_next = False
        while j < len(a):
            ch = a[j]
            if ch in RUN_BOOL_SHORT:
                j += 1
                continue
            tail = a[j + 1:]
            if tail:
                val = tail
            else:
                val = args[i + 1] if i + 1 < len(args) else ""
                consumed_next = not val.startswith("-") or ch == "p"
            if ch == "p" and fixed_host_port(val):
                return RUN_MSG.format(sub=sub, spec=val.lstrip("="))
            break
        i += 2 if consumed_next else 1
    return None


def check_compose(args: list[str], label: str, via_xargs: bool) -> str | None:
    i, dry_run = 0, False
    while i < len(args):
        a = args[i]
        if a == "--dry-run":
            dry_run = True
        if a.startswith("-"):
            name = a.split("=", 1)[0]
            i += 2 if (name in COMPOSE_GLOBAL_VALUE and "=" not in a) else 1
            continue
        break
    rest = args[i:]
    if not rest:
        return (f"`{label}` gets its subcommand from xargs input, which this guard can't see. "
                "Run the compose command directly (`dcup up` to start).") if via_xargs else None
    sub, sub_args = rest[0], rest[1:]
    if dry_run or "--help" in sub_args or "-h" in sub_args:
        return None
    if sub in ("up", "create"):
        return UP_MSG.format(cmd=f"{label} {sub}")
    if sub == "run":
        for a in sub_args:
            if a == "--service-ports" or a in ("-p", "--publish") or a.startswith("--publish="):
                return UP_MSG.format(cmd=f"{label} run {a}")
            if re.fullmatch(r"-[a-zA-Z]*p.*", a) and not a.startswith("--"):
                return UP_MSG.format(cmd=f"{label} run {a}")
            if not a.startswith("-"):
                break
    return None


def check_docker(args: list[str], via_xargs: bool) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if not a.startswith("-"):
            break
        i += 2 if (a in DOCKER_GLOBAL_VALUE) else 1
    rest = args[i:]
    if not rest:
        return None
    sub = rest[0]
    if sub == "compose":
        return check_compose(rest[1:], "docker compose", via_xargs)
    if sub == "container" and len(rest) > 1:
        sub, rest = rest[1], rest[1:]
        label = f"container {sub}"
    else:
        label = sub
    if sub in ("run", "create"):
        return check_run(label, rest[1:])
    return None


def analyze_words(words: list[str], depth: int) -> list[str]:
    words, scripts, via_xargs, _ = unwrap(words)
    reasons: list[str] = []
    for s in scripts:
        reasons += analyze(s, depth + 1)
    if not words:
        return reasons
    head = words[0]
    b = _base(head)
    args = words[1:]
    r = None
    if b == "docker":
        r = check_docker(args, via_xargs)
    elif b in ("docker-compose", "podman-compose"):
        r = check_compose(args, b, via_xargs)
    elif b == "dcup":
        if args and args[0] == "--bypass":
            r = check_compose(args[1:], "dcup --bypass", via_xargs)
    elif head.startswith("$"):
        # Runtime-built command name (`$D compose up`): judge the visible words.
        if "compose" in args:
            r = check_compose(args[args.index("compose") + 1:], f"{head} compose", via_xargs)
        elif args[:1] in (["run"], ["create"]):
            r = check_run(args[0], args[1:])
    if r:
        reasons.append(r)
    return reasons


def analyze(script: str, depth: int = 0) -> list[str]:
    if depth > MAX_DEPTH:
        return (["command nests shells too deeply for the dcup guard to check; flatten it"]
                if re.search(r"docker|dcup|compose", script) else [])
    cmds, nested = parse(script)
    reasons: list[str] = []
    for body in nested:
        reasons += analyze(body, depth + 1)
    for cmd in cmds:
        reasons += analyze_words(cmd.words, depth)
        _, _, _, stdin_shell = unwrap(list(cmd.words))
        if stdin_shell:
            for text in cmd.stdin_texts:
                reasons += analyze(text, depth + 1)
            src = cmd.piped_from
            if src is not None:
                for text in src.stdin_texts:
                    reasons += analyze(text, depth + 1)
                src_words, _, _, _ = unwrap(list(src.words))
                if src_words and _base(src_words[0]) in ("echo", "printf", "cat"):
                    reasons += analyze(" ".join(a for a in src_words[1:] if not a.startswith("-")),
                                       depth + 1)
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ── hook entry point ──────────────────────────────────────────────────────────

def _log(line: str) -> None:
    try:
        state = Path(__file__).resolve().parents[2] / "state"
        if state.is_dir():
            with open(state / "hook-blocks.log", "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass


def main() -> int:
    if os.environ.get("DCUP_GUARD", "").lower() in ("off", "0", "false", "no"):
        return 0
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if data.get("tool_name", "Bash") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(cmd, str) or not cmd.strip():
        return 0
    # No keyword pre-filter: `d''ocker` and `\docker` spell docker without the substring.
    try:
        reasons = analyze(cmd)
    except Exception as exc:  # noqa: BLE001 — a guard bug must not block every Bash call
        print(f"dcup-guard: internal error ({exc!r}); command allowed unchecked", file=sys.stderr)
        _log(f"ERROR dcup-guard {exc!r} cmd={cmd[:120]!r}")
        return 0
    if not reasons:
        return 0
    print("BLOCKED by dcup-guard (port registry):", file=sys.stderr)
    for r in reasons:
        print(f"  - {r}", file=sys.stderr)
    print("Registry: `dcup list`. Read-only docker commands are never blocked.", file=sys.stderr)
    flat = " ".join(cmd.split())[:120]
    _log(f"BLOCKED dcup-guard cmd={flat} session={data.get('session_id', '')}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
