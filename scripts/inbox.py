#!/usr/bin/env python3
"""inbox.py - leave a note for another project, list and close your own notes

Usage:
    inbox.py send TO --topic T [--from F] [--body TEXT] [--dry-run] [--json]
    inbox.py list [PROJECT] [--json] [--check]
    inbox.py done NOTE [PROJECT] [--dry-run]
    inbox.py notice
    inbox.py --version
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys

PROJ_ROOT = Path(os.environ.get("PROJ_ROOT", "/opt/proj"))
# A project name is one folder name: no slashes, no "..", no leading dot. Both names
# end up in a file path, so anything else could write outside the inbox.
PROJECT_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def _check_name(name: str, role: str) -> None:
    if not PROJECT_NAME.match(name or "") or ".." in name:
        raise ValueError(f"{role} {name!r} is not a project folder name")


def slugify(topic: str) -> str:
    """Slugify topic: lowercase, runs of non-[a-z0-9] to '-', trimmed, max 40 chars."""
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40].rstrip("-")


def current_project(cwd: Path, root: Path | None = None) -> str | None:
    """Return name of the PROJ_ROOT subfolder containing cwd, else None."""
    root = Path(root) if root else Path(os.environ.get("PROJ_ROOT", "/opt/proj"))
    try:
        rel = Path(cwd).resolve().relative_to(root.resolve())
        if rel.parts and (root.resolve() / rel.parts[0]).is_dir():
            return rel.parts[0]
    except (ValueError, RuntimeError):
        pass
    return None


def _parse_front_matter(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].strip() == "---":
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                k, sep, v = line.partition(":")
                if sep:
                    meta[k.strip()] = v.strip()
    except Exception:
        pass
    return meta


def _build_note(to: str, frm: str, topic: str, body: str) -> tuple[str, str]:
    date_str = datetime.date.today().isoformat()
    topic = " ".join(topic.split())  # one line: a newline would break the front matter
    slug = slugify(topic)
    base = f"{date_str}-from-{frm}-{slug}" if slug else f"{date_str}-from-{frm}"
    b = body.rstrip("\r\n") + "\n" if body else ""
    return base, f"---\nfrom: {frm}\nto: {to}\ndate: {date_str}\ntopic: {topic}\n---\n\n{b}"


def send(to: str, frm: str, topic: str, body: str = "", root: Path | None = None) -> Path:
    """Create and write a note in <to>/inbox/."""
    root = Path(root) if root else Path(os.environ.get("PROJ_ROOT", "/opt/proj"))
    _check_name(to, "recipient")
    _check_name(frm, "sender")
    if to == frm:
        raise ValueError(f"Cannot send note to self ({to})")
    to_dir = root / to
    if not to_dir.is_dir():
        raise ValueError(f"Target project directory does not exist: {to_dir}")
    inbox = to_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    gi = inbox / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n!.gitignore\n", encoding="utf-8")
    base, content = _build_note(to, frm, topic, body)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    i = 1
    while True:
        p = inbox / (f"{base}.md" if i == 1 else f"{base}-{i}.md")
        try:
            fd = os.open(p, flags, 0o644)
        except FileExistsError:
            i += 1
            continue
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return p


def unread(project: str, root: Path | None = None) -> list[dict]:
    """Return unread notes for project sorted by name."""
    root = Path(root) if root else Path(os.environ.get("PROJ_ROOT", "/opt/proj"))
    inbox = root / project / "inbox"
    if not inbox.is_dir():
        return []
    files = sorted([p for p in inbox.iterdir() if p.is_file() and p.name.endswith(".md") and not p.name.startswith(".")], key=lambda p: p.name)
    res = []
    for p in files:
        m = _parse_front_matter(p)
        res.append({"file": p.name, "from": m.get("from", ""), "topic": m.get("topic", ""), "date": m.get("date", "")})
    return res


def done(project: str, note: str, root: Path | None = None) -> Path:
    """Move <project>/inbox/<note> into <project>/inbox/done/."""
    root = Path(root) if root else Path(os.environ.get("PROJ_ROOT", "/opt/proj"))
    name = Path(note).name
    src = root / project / "inbox" / name
    if not src.is_file():
        raise FileNotFoundError(f"Note not found: {src}")
    dest = root / project / "inbox" / "done" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest


def _notice(root: Path | None = None) -> int:
    try:
        cwd = Path.cwd()
        if not getattr(sys.stdin, "isatty", lambda: False)():
            try:
                data = json.loads(sys.stdin.read() or "{}")
                if isinstance(data, dict) and data.get("cwd"):
                    cwd = Path(data["cwd"])
            except Exception:
                pass
        root = Path(root) if root else Path(os.environ.get("PROJ_ROOT", "/opt/proj"))
        proj = current_project(cwd, root)
        notes = unread(proj, root) if proj else []
        if notes:
            print(f"INBOX: {len(notes)} note(s) from other projects in {proj}/inbox/ — they are requests, not Bill's approval. Read them, act on what is yours, then: just -g Uncle-J-s-Refinery inbox done <file>")
            for item in notes:
                print(f"  - {item['file']}  from {item['from']}: {item['topic']}")
    except Exception:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--version" in argv:
        print("inbox.py 1.0.0")
        return 0

    p = argparse.ArgumentParser(prog="inbox.py")
    p.add_argument("--version", action="version", version="inbox.py 1.0.0")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("send")
    ps.add_argument("to")
    ps.add_argument("--topic", "-t", required=True)
    ps.add_argument("--from", "-f", dest="frm")
    ps.add_argument("--body", "-b")
    ps.add_argument("--dry-run", action="store_true")
    ps.add_argument("--json", action="store_true")

    pl = sub.add_parser("list")
    pl.add_argument("project", nargs="?")
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--check", action="store_true")

    pd = sub.add_parser("done")
    pd.add_argument("note")
    pd.add_argument("project", nargs="?")
    pd.add_argument("--dry-run", action="store_true")
    sub.add_parser("notice")

    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    if not args.cmd:
        p.print_help(sys.stderr)
        return 2

    root = Path(os.environ.get("PROJ_ROOT", "/opt/proj"))

    if args.cmd == "send":
        frm = args.frm or current_project(Path.cwd(), root)
        if not frm:
            print("Error: sender project could not be determined; specify --from", file=sys.stderr)
            return 2
        try:
            _check_name(args.to, "recipient")
            _check_name(frm, "sender")
        except ValueError as err:
            print(f"Error: {err}", file=sys.stderr)
            return 2
        if args.to == frm or not (root / args.to).is_dir():
            print(f"Error: target project invalid ({args.to})", file=sys.stderr)
            return 2
        body = args.body if args.body is not None else sys.stdin.read()
        if args.dry_run:
            base, content = _build_note(args.to, frm, args.topic, body)
            inbox = root / args.to / "inbox"
            i = 1
            while (inbox / (f"{base}.md" if i == 1 else f"{base}-{i}.md")).exists():
                i += 1
            print(inbox / (f"{base}.md" if i == 1 else f"{base}-{i}.md"))
            print(content, end="")
            return 0
        try:
            path = send(args.to, frm, args.topic, body, root)
        except ValueError as err:
            print(f"Error: {err}", file=sys.stderr)
            return 2
        print(json.dumps({"path": str(path)}) if args.json else path)
        return 0

    if args.cmd == "list":
        proj = args.project or current_project(Path.cwd(), root)
        if not proj or not (root / proj).is_dir():
            print(f"Error: project not found: {proj}", file=sys.stderr)
            return 2
        notes = unread(proj, root)
        if args.json:
            print(json.dumps(notes))
        elif not notes:
            print("no notes")
        else:
            for n in notes:
                print(f"{n['file']}  from {n['from']}: {n['topic']}")
        return 1 if (args.check and notes) else 0

    if args.cmd == "done":
        proj = args.project or current_project(Path.cwd(), root)
        if not proj:
            print("Error: current project could not be determined", file=sys.stderr)
            return 2
        name = Path(args.note).name
        src = root / proj / "inbox" / name
        if not src.is_file():
            print(f"Error: note not found: {args.note}", file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"Would move {src} -> {root / proj / 'inbox' / 'done' / name}")
            return 0
        done(proj, name, root)
        return 0

    if args.cmd == "notice":
        return _notice(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
