#!/usr/bin/env python3
"""Shared RAM gate: one place every session asks before starting something heavy on this host.

Why: on 11-24 a test VM, the host's Ollama on CPU and Heretic used up dma64's memory and swap;
nothing was killed and the machine hung until it was reset. Each session saw "enough free" on
its own, because none could see what the others were about to start.

How: a grant is a lease, `--gib N` for `--ttl` seconds (the start-up window). MemAvailable
already counts memory a VM or model has taken, so a lease only covers the part not yet taken:
it shrinks linearly from N to 0 over its TTL (a started VM isn't counted twice for long).
A request is granted when

    MemAvailable - (what live leases still hold) - N >= FLOOR (6 GiB)

All of it runs under one flock, so two sessions can't both pass on the same free memory.
Asking again with the same label replaces that label's lease (a retried start doesn't stack).
On refusal it names the leases and the biggest processes, so the caller knows what to stop.

    ram_gate.py acquire --gib 8 --label "mtw2 test VM" [--ttl 600]   # prints the lease id; exit 1 = refused
    ram_gate.py release ID          # once the load is done (or failed), so others needn't wait
    ram_gate.py status
    ram_gate.py hook                # PreToolUse JSON on stdin (hooks/discipline/ram-gate.sh)

The hook covers `virsh start|create`, `virt-install` and `qemu-system-*` run on this machine. The
program must be in command position (after sudo/env/VAR=/timeout/nice or a do/then keyword), so
`ssh host virsh start`, `grep virt-install`, heredoc bodies and commit messages pass, as do a
remote libvirt URI (`-c qemu+ssh://host/…`, LIBVIRT_DEFAULT_URI), --help/--version/--dry-run/
--print-xml, and `virsh start` of a domain that is already running. Not seen: starts inside
`bash -c "…"`, a script or a just recipe; those call `acquire` themselves, as model loads do
(Python callers use `lease()`: comfy_job's Qwen jobs, ask_local's model loads and
local_chat's Heretic wakes, each only when a load is actually coming).
It sizes the VM from `--memory`/`-m`, the domain's XML or `virsh dominfo`, and assumes 8 GiB when
it can't tell. A command holding `# ram-gate: ok <reason>` skips the check (say why).

Env (tests and other hosts): RAM_GATE_DIR (lease store, default ~/.claude/state/ram-gate),
RAM_GATE_MEMINFO (default /proc/meminfo), RAM_GATE_FLOOR_GIB (default 6), RAM_GATE_OFF=1
(Python callers skip leasing; the hook and the CLI ignore it).
Exit: 0 granted, 1 refused (or the lock stayed busy 10 s), 2 usage error or hook block.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

GIB = 1024 ** 3
DEFAULT_TTL = 600          # a guest touches its memory over minutes, not seconds
DEFAULT_VM_GIB = 8.0
LOCK_WAIT = 10.0           # under the hook's 15 s timeout
SKIP = re.compile(r"#\s*ram-gate:\s*ok\s+\S")
SEPARATORS = set(";&|()\n")
# words that can stand before the program, and per word the flags that take a value
PREFIX = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "-R"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "timeout": {"-s", "-k"},
    "xargs": {"-n", "-I", "-P", "-L", "-d", "-a", "-s", "-E"},
    "nohup": set(), "exec": set(), "command": set(), "time": set(), "stdbuf": set(),
    "do": set(), "then": set(), "else": set(), "elif": set(), "if": set(), "while": set(),
    "until": set(), "!": set(), "{": set(),
}
NOT_A_START = {"--help", "-h", "--version", "-help", "-version", "--dry-run", "--print-xml", "help", "?"}
VIRSH_VALUE_FLAGS = {"-c", "--connect", "-d", "--debug", "-e", "--escape", "-k", "--keepalive-interval",
                     "-K", "--keepalive-count", "-l", "--log"}


def store() -> Path:
    return Path(os.environ.get("RAM_GATE_DIR") or Path.home() / ".claude" / "state" / "ram-gate")


def floor_gib() -> float:
    try:
        return float(os.environ.get("RAM_GATE_FLOOR_GIB", "6"))
    except ValueError:
        return 6.0


def available_bytes() -> int | None:
    path = os.environ.get("RAM_GATE_MEMINFO", "/proc/meminfo")
    try:
        text = Path(path).read_text()
    except OSError:
        return None
    m = re.search(r"^MemAvailable:\s+(\d+) kB", text, re.M)
    return int(m.group(1)) * 1024 if m else None


class Locked:
    """flock on the store's lock file, given up after LOCK_WAIT (TimeoutError). fcntl is imported
    here, not at module scope: a module-level import broke pytest collection on Windows once."""

    def __enter__(self):
        import fcntl
        d = store()
        d.mkdir(parents=True, exist_ok=True)
        self.f = open(d / "lock", "w")
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > deadline:
                    self.f.close()
                    raise TimeoutError(f"ram-gate lock {d / 'lock'} busy for {LOCK_WAIT:g} s")
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.f.close()


def held_gib(lease: dict, now: float) -> float:
    """What a lease still holds: its size, shrinking linearly to 0 at expiry."""
    span = lease["expires"] - lease.get("created", lease["expires"] - DEFAULT_TTL)
    if span <= 0:
        return 0.0
    return lease["gib"] * max(0.0, min(1.0, (lease["expires"] - now) / span))


def load_leases(now: float) -> list[dict]:
    try:
        data = json.loads((store() / "leases.json").read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and isinstance(x.get("gib"), (int, float))
            and isinstance(x.get("expires"), (int, float)) and x["expires"] > now]


def save_leases(leases: list[dict]) -> None:
    p = store() / "leases.json"
    tmp = p.with_name(f"leases.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(leases, indent=1))
    os.replace(tmp, p)


def top_users(n: int = 5) -> list[str]:
    rows = []
    for d in Path("/proc").iterdir() if Path("/proc").is_dir() else []:
        if not d.name.isdigit():
            continue
        try:
            status = (d / "status").read_text()
        except OSError:
            continue
        name = re.search(r"^Name:\s+(.+)$", status, re.M)
        rss = re.search(r"^VmRSS:\s+(\d+) kB", status, re.M)
        if name and rss:
            nm = name.group(1).strip()
            if nm.startswith("qemu"):                 # name the VM, not just "qemu-system-x86"
                try:
                    argv = (d / "cmdline").read_bytes().split(b"\0")
                    g = argv[argv.index(b"-name") + 1].decode(errors="replace")
                    nm += " " + re.sub(r"^guest=([^,]*).*", r"\1", g)
                except (OSError, ValueError, IndexError):
                    pass
            rows.append((int(rss.group(1)) * 1024, nm, d.name))
    rows.sort(reverse=True)
    return [f"{nm} (pid {pid}) {b / GIB:.1f} GiB" for b, nm, pid in rows[:n]]


def acquire(gib: float, label: str, ttl: int, now: float | None = None) -> tuple[bool, str]:
    """(granted, lease id or reason). Unreadable meminfo grants: a gate that can't measure must
    not stop every start on a host without /proc (the reason says so)."""
    now = time.time() if now is None else now
    with Locked():
        leases = [x for x in load_leases(now) if x.get("label") != label]   # same label = retry
        avail = available_bytes()
        if avail is None:
            return True, "unmeasured: MemAvailable unreadable, granted without a lease"
        held = sum(held_gib(x, now) for x in leases) * GIB
        left = avail - held - gib * GIB
        if left < floor_gib() * GIB:
            parts = [f"needs {gib:g} GiB for {label!r}; MemAvailable is {avail / GIB:.1f} GiB"]
            if leases:
                parts.append("already leased: " + ", ".join(
                    f"{x.get('label', '?')} {held_gib(x, now):.1f} of {x['gib']:g} GiB "
                    f"({int(x['expires'] - now)} s left, id {x.get('id')})" for x in leases))
            parts.append(f"that leaves {left / GIB:.1f} GiB, under the {floor_gib():g} GiB floor")
            users = top_users()
            if users:
                parts.append("biggest: " + "; ".join(users))
            return False, ". ".join(parts)
        lease = {"id": uuid.uuid4().hex[:12], "gib": gib, "label": label,
                 "created": now, "expires": now + ttl}
        leases.append(lease)
        save_leases(leases)
        return True, lease["id"]


def release(lease_id: str) -> bool:
    with Locked():
        leases = load_leases(time.time())
        kept = [x for x in leases if x.get("id") != lease_id]
        save_leases(kept)
        return len(kept) != len(leases)


class Refused(Exception):
    """The gate said no (or its lock stayed busy); str() is the reason, naming what to stop."""


def enabled() -> bool:
    """RAM_GATE_OFF=1 turns the Python callers' leasing (and their load probes) off."""
    return os.environ.get("RAM_GATE_OFF") != "1"


@contextlib.contextmanager
def lease(gib: float, label: str, ttl: int = DEFAULT_TTL):
    """Hold a lease around a model load or job, for Python callers (comfy_job, ask_local,
    local_chat). Raises Refused before the body runs; releases on the way out, however the
    body ends. Fails open: gib <= 0 or RAM_GATE_OFF=1 skips it, and a gate that can't run
    (no fcntl on Windows, an unwritable store) lets the body run ungated."""
    if gib <= 0 or not enabled():
        yield None
        return
    try:
        ok, msg = acquire(gib, label, ttl)
    except TimeoutError as e:
        raise Refused(str(e)) from e
    except Exception:                       # noqa: BLE001 — a broken gate must not stop loads
        ok, msg = True, "unmeasured: ram gate unavailable"
    if not ok:
        raise Refused(msg)
    try:
        yield msg
    finally:
        if not msg.startswith("unmeasured"):
            try:
                release(msg)
            except Exception:               # noqa: BLE001 — it expires on its own
                pass


def status() -> dict:
    now = time.time()
    with Locked():
        leases = load_leases(now)
    avail = available_bytes()
    return {"mem_available_gib": None if avail is None else round(avail / GIB, 1),
            "floor_gib": floor_gib(),
            "leases": [{**x, "seconds_left": int(x["expires"] - now),
                        "holds_gib": round(held_gib(x, now), 2)} for x in leases]}


# ── hook: find and size a VM start ───────────────────────────────────────────────────

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([\w.-]+)\1")


def drop_heredoc_bodies(cmd: str) -> str:
    """Remove heredoc bodies (they are data, not commands); keep the opener line."""
    out, end = [], None
    for line in cmd.split("\n"):
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = _HEREDOC.search(line)
        if m:
            end = m.group(2)
    return "\n".join(out)


def simple_commands(cmd: str) -> list[list[str]]:
    """The command's words split into simple commands, quote-aware (a `;` inside a quoted
    commit message is not a separator). Unparseable input gives []: the hook fails open."""
    lex = shlex.shlex(drop_heredoc_bodies(cmd), posix=True, punctuation_chars=";&|()\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""          # `a#b` is a word; a real comment line can't put a program first
    out, cur = [], []
    try:
        for tok in lex:
            if tok and set(tok) <= SEPARATORS:
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append(tok)
    except ValueError:
        return []
    if cur:
        out.append(cur)
    return out


def _strip_prefix(words: list[str]) -> tuple[list[str], dict[str, str]]:
    """(the words from the program on, VAR=value assignments seen before it)."""
    i, assigns = 0, {}
    while i < len(words):
        w = words[i]
        m = re.match(r"^([A-Za-z_]\w*)=(.*)$", w)
        if m:
            assigns[m.group(1)] = m.group(2)
            i += 1
        elif w in PREFIX:
            takes = PREFIX[w]
            i += 1
            while i < len(words) and words[i].startswith("-") and words[i] != "-":
                if words[i] == "--":
                    i += 1
                    break
                i += 2 if words[i] in takes else 1
            if w == "timeout" and i < len(words):                # timeout 30 virsh start …
                i += 1
        else:
            break
    return words[i:], assigns


def _virsh_rest(args: list[str]) -> tuple[list[str], list[str]]:
    """(connection flags, the rest from the subcommand on), skipping virsh's global options."""
    conn, rest = [], list(args)
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in ("-c", "--connect") and rest:
            conn += [flag, rest.pop(0)]
        elif flag.startswith("--connect="):
            conn.append(flag)
        elif flag in VIRSH_VALUE_FLAGS and rest:
            rest.pop(0)
    return conn, rest


def _uri(args: list[str], assigns: dict[str, str]) -> str:
    for i, a in enumerate(args):
        if a in ("-c", "--connect") and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--connect="):
            return a.split("=", 1)[1]
    return assigns.get("LIBVIRT_DEFAULT_URI") or os.environ.get("LIBVIRT_DEFAULT_URI", "")


def is_remote(uri: str) -> bool:
    """qemu+ssh://host/system or qemu://host/system: another machine's memory, not ours."""
    m = re.match(r"^[\w+.-]+://([^/]*)", uri)
    return bool(m and m.group(1) and m.group(1) not in ("localhost", "127.0.0.1"))


def vm_starts(cmd: str) -> list[list[str]]:
    """Each simple command that starts a VM on this machine, prefix words removed."""
    out = []
    for words in simple_commands(cmd):
        w, assigns = _strip_prefix(words)
        if not w:
            continue
        prog, args = os.path.basename(w[0]), w[1:]
        if any(a in NOT_A_START for a in args):
            continue
        if prog == "virt-install" or prog.startswith("qemu-system-"):
            if prog == "virt-install" and is_remote(_uri(args, assigns)):
                continue
            out.append([prog, *args])
        elif prog == "virsh":
            conn, rest = _virsh_rest(args)
            if rest and rest[0] in ("start", "create") and not is_remote(_uri(conn, assigns)):
                out.append([prog, *args])
    return out


def _size_gib(v: str) -> float | None:
    """qemu `-m` value: plain number = MiB; K/M/G/T suffixes."""
    m = re.match(r"(\d+(?:\.\d+)?)([KMGT]?)", v.strip(), re.I)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).upper()
    return {"": n / 1024, "M": n / 1024, "K": n / 1024 / 1024, "G": n, "T": n * 1024}[unit]


def _xml_gib(xml: str) -> float | None:
    m = re.search(r"<memory(?:\s+unit=['\"](\w+)['\"])?\s*>(\d+)</memory>", xml)
    if not m:
        return None
    unit, n = (m.group(1) or "KiB").lower(), int(m.group(2))
    scale = {"b": 1, "bytes": 1, "k": 1024, "kib": 1024, "m": 1024 ** 2, "mib": 1024 ** 2,
             "g": GIB, "gib": GIB}.get(unit, 1024)
    return n * scale / GIB


def vm_gib(words: list[str], run=subprocess.run) -> tuple[float, str]:
    """(GiB, how it was found) for one VM-starting command; 0 = nothing new will start."""
    prog, args = words[0], words[1:]
    if prog == "virt-install":
        for i, w in enumerate(args):
            for flag in ("--memory", "--ram"):
                if w == flag and i + 1 < len(args):
                    val = args[i + 1]
                elif w.startswith(flag + "="):
                    val = w.split("=", 1)[1]
                else:
                    continue
                m = re.search(r"(?:^|,|memory=|maxmemory=)(\d+)", val)
                if m:
                    return int(m.group(1)) / 1024, "virt-install --memory"
    elif prog.startswith("qemu-system-"):
        for i, w in enumerate(args):
            val = args[i + 1] if w == "-m" and i + 1 < len(args) else None
            if val:
                g = _size_gib(val.split(",")[0].replace("size=", ""))
                if g:
                    return g, "qemu -m"
        return 0.125, "qemu default -m"
    elif prog == "virsh":
        conn, rest = _virsh_rest(args)
        target = [a for a in rest[1:] if not a.startswith("-")]
        if target and rest[0] == "create":
            try:
                g = _xml_gib(Path(target[0]).read_text())
                if g:
                    return g, "domain XML"
            except OSError:
                pass
        elif target:
            try:
                r = run(["virsh", *conn, "dominfo", target[0]], capture_output=True, text=True, timeout=5)
                out = r.stdout or ""
                if re.search(r"^State:\s+running", out, re.M):
                    return 0.0, "already running"
                m = re.search(r"^Max memory:\s+(\d+) KiB", out, re.M)
                if m:
                    return int(m.group(1)) / 1024 / 1024, "virsh dominfo"
            except (OSError, subprocess.SubprocessError):
                pass
    return DEFAULT_VM_GIB, "assumed"


def hook(data: dict, run=subprocess.run) -> str | None:
    """The refusal message, or None to let the call run. A granted start keeps its (shrinking)
    lease, so a model load in another session sees the VM's memory as taken meanwhile."""
    if data.get("tool_name") not in (None, "Bash"):
        return None
    cmd = (data.get("tool_input") or {}).get("command") or ""
    if not cmd or SKIP.search(cmd):
        return None
    starts = vm_starts(cmd)
    if not starts:
        return None
    total, how = 0.0, []
    for words in starts:
        g, src = vm_gib(words, run)
        total += g
        how.append(f"{g:g} GiB ({src})")
    if total <= 0:
        return None
    ok, msg = acquire(total, "VM: " + " ".join(starts[0])[:60], DEFAULT_TTL)
    if ok:
        return None
    return (f"ram-gate: VM start refused. {msg}. VM size: {', '.join(how)}. On 11-24 a VM start "
            "here hung dma64 until it was reset. Free memory first, use another machine, or add "
            "`# ram-gate: ok <reason>` if you know it fits.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("acquire")
    a.add_argument("--gib", type=float, required=True)
    a.add_argument("--label", required=True)
    a.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    r = sub.add_parser("release")
    r.add_argument("id")
    sub.add_parser("status")
    sub.add_parser("hook")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "acquire":
            if args.gib <= 0 or args.ttl <= 0:
                print("ram-gate: --gib and --ttl must be positive", file=sys.stderr)
                return 2
            ok, msg = acquire(args.gib, args.label, args.ttl)
            if ok:
                print(msg)
                return 0
            print(f"ram-gate: refused. {msg}", file=sys.stderr)
            return 1
        if args.cmd == "release":
            if not release(args.id):
                print(f"ram-gate: no live lease {args.id}", file=sys.stderr)
            return 0
        if args.cmd == "status":
            print(json.dumps(status(), indent=1))
            return 0
    except TimeoutError as e:
        print(f"ram-gate: refused. {e}", file=sys.stderr)
        return 1
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    msg = hook(data)              # a TimeoutError here is a traceback, exit 1: the wrapper passes
    if msg:
        print(msg, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
