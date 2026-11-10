#!/usr/bin/env python3
"""tool_miner.py - list jobs agents keep doing by hand, as candidates for tools

read-only: it reads Claude Code transcripts and prints; it changes nothing.

PURPOSE:
    Find jobs a Claude Code agent does by hand again and again across sessions,
    so they can become ready-made tools (docs/TOOLS-STANDARD.md). Commands that
    already call a tool (a `just` recipe, a .sh/.py script) are left out unless
    --include-tools, and one-step commands unless --min-steps 1.

HOW TO RUN:
    just tool-mine
    # or:
    python3 scripts/tool_miner.py --root ~/.claude/projects --min-sessions 3

SAMPLE OUTPUT:
    Sessions  Projects  Uses  Shape           Example
    -------------------------------------------------
    5         2         12    git commit      git commit -m "initial commit"
    3         1         8     docker compose  docker compose up -d
"""

from __future__ import annotations

import argparse
import json
import math
import posixpath
import re
import shlex
import sys
import time
from pathlib import Path

TRIVIAL = {
    "ls", "cat", "cd", "echo", "printf", "head", "tail", "grep", "rg",
    "pwd", "wc", "find", "sed", "awk", "cut", "sort", "uniq", "true",
    "test", "[", "which", "tr", "xargs", "date", "sleep",
}

# Words that wrap the real command: `timeout 600 pytest` is a pytest run.
WRAPPERS = {"sudo", "env", "nice", "time", "command", "exec", "nohup"}

VERSION = "1.0.0"

TWO_WORD_TRIVIAL = {
    "git status", "git log", "git diff", "git show", "git fetch",
}


def _is_number(s: str) -> bool:
    """Return True if string represents a number."""
    if not s:
        return False
    if s.isdigit():
        return True
    try:
        val = float(s)
        return not (math.isnan(val) or math.isinf(val))
    except ValueError:
        return False


def _is_quoted(s: str) -> bool:
    """Return True if string starts with a quote character."""
    return s.startswith(('"', "'"))


CONTROL = {"for", "do", "done", "while", "until", "if", "then", "elif", "else", "fi",
           "case", "esac", "{", "}", "(", ")", "!"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


# 2>&1, &>/dev/null, >file, 2>> log, <input: plumbing, not steps.
REDIRECT = re.compile(r"\d*>&\d+|&>>?\s*[^\s;&|\"']+|\d*>>?\s*[^\s;&|\"']+|<\s*[^\s;&|<\"']+")


def _strip_heredocs(command: str) -> str:
    """Drop heredoc bodies: their lines are data, not commands."""
    out, marker = [], None
    for line in command.splitlines():
        if marker is not None:
            if line.strip() == marker:
                marker = None
            continue
        found = HEREDOC.search(line)
        out.append(HEREDOC.sub("", line) if found else line)
        if found:
            marker = found.group(2)
    return "\n".join(out)


def _segments(command: str) -> list[list[str]]:
    """Words of each simple command, split on ; & | && || and newlines, quote-aware."""
    text = REDIRECT.sub(" ", _strip_heredocs(command))
    lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = [[]]
    try:
        for token in lexer:
            if token and set(token) <= set(";&|()\n"):
                segments.append([])
            else:
                segments[-1].append(token)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        return [seg.split() for seg in re.split(r"&&|\|\||[;\n|]", text)]
    return [seg for seg in segments if seg]


def shape_of(command: str) -> str:
    """Normalize a shell command into a high-level tool shape.

    - Splits on &&, ||, ;, |, and newlines.
    - Drops leading VAR=val assignments and sudo.
    - Drops cd <dir> segments entirely.
    - Retains first word (basename if path) plus second word if non-flag,
      non-number, non-quoted. Basename used for second word if path or .py/.sh.
    - Drops segments whose heads are in TRIVIAL or TWO_WORD_TRIVIAL.
    - Joins remaining segment heads with ' && ', collapsing consecutive duplicates.
    """
    if not command or not command.strip():
        return ""

    heads: list[str] = []

    for words in _segments(command):
        if not words or words[0] in ("for", "select", "case"):  # `for x in a b c`: the loop header
            continue
        while words and words[0] in CONTROL:
            words = words[1:]
        if not words:
            continue

        # Strip leading VAR=val assignments and sudo
        while words:
            w = words[0]
            if w in WRAPPERS:
                words.pop(0)
            elif w == "timeout":
                words.pop(0)
                if words and (_is_number(words[0].rstrip("smhd")) or words[0].startswith("-")):
                    words.pop(0)
            elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
                words.pop(0)
            else:
                break

        if not words:
            continue

        # cd <dir> segments are dropped entirely
        first_base = posixpath.basename(words[0]) if "/" in words[0] else words[0]
        if first_base == "cd":
            continue

        w1 = first_base.strip()
        if not w1:
            continue

        w2: str | None = None
        if len(words) > 1:
            cand = words[1]
            if not cand.startswith("-") and not _is_number(cand) and not _is_quoted(cand):
                if "/" in cand or cand.endswith((".py", ".sh")):
                    cand = posixpath.basename(cand)
                w2 = cand

        head = f"{w1} {w2}" if w2 else w1

        # Drop trivial heads
        if w1 in TRIVIAL or head in TRIVIAL or head in TWO_WORD_TRIVIAL:
            continue

        heads.append(head)

    # Collapse consecutive duplicates
    collapsed: list[str] = []
    for h in heads:
        if not collapsed or collapsed[-1] != h:
            collapsed.append(h)

    return " && ".join(collapsed)


def is_tool_call(head: str) -> bool:
    """A segment that already runs a ready-made tool: a just recipe or a script."""
    words = head.split()
    if not words:
        return True
    return words[0] == "just" or any(w.endswith((".py", ".sh")) for w in words)


def without_tool_calls(shape: str) -> str:
    return " && ".join(h for h in shape.split(" && ") if h and not is_tool_call(h))


def steps(shape: str) -> int:
    return len(shape.split(" && ")) if shape else 0


def mine(root: Path, since_days: int, include_tools: bool = True) -> list[dict]:
    """Mine recurring command shapes from transcript JSONL files under root.

    Input shape: <root>/<project-dir>/<session-id>.jsonl
    Subfolders inside project-dirs are ignored.
    """
    root = Path(root)
    if not root.exists() or not root.is_dir():
        return []

    cutoff = time.time() - (since_days * 86400.0) if since_days > 0 else None

    # shape -> {sessions: set(), projects: set(), uses: int, example: str}
    stats: dict[str, dict] = {}

    try:
        project_dirs = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return []

    for project_dir in project_dirs:
        if not project_dir.is_dir():
            continue

        try:
            session_files = sorted(project_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            continue

        for file_path in session_files:
            if not file_path.is_file() or file_path.suffix != ".jsonl":
                continue

            if cutoff is not None:
                try:
                    if file_path.stat().st_mtime < cutoff:
                        continue
                except OSError:
                    continue

            session_id = (project_dir.name, file_path.name)

            try:
                with file_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(record, dict):
                            continue
                        if record.get("type") != "assistant":
                            continue
                        msg = record.get("message")
                        if not isinstance(msg, dict):
                            continue
                        content = msg.get("content")
                        if not isinstance(content, list):
                            continue

                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "tool_use" and item.get("name") == "Bash":
                                inp = item.get("input")
                                if not isinstance(inp, dict):
                                    continue
                                cmd = inp.get("command")
                                if not isinstance(cmd, str):
                                    continue

                                shape = shape_of(cmd)
                                if not include_tools:
                                    shape = without_tool_calls(shape)
                                if not shape:
                                    continue

                                if shape not in stats:
                                    stats[shape] = {
                                        "sessions": set(),
                                        "projects": set(),
                                        "uses": 0,
                                        "example": cmd[:200],
                                    }
                                entry = stats[shape]
                                entry["sessions"].add(session_id)
                                entry["projects"].add(project_dir.name)
                                entry["uses"] += 1
            except OSError:
                continue

    results = [
        {
            "shape": shape,
            "sessions": len(data["sessions"]),
            "projects": len(data["projects"]),
            "uses": data["uses"],
            "example": data["example"],
        }
        for shape, data in stats.items()
    ]

    results.sort(key=lambda x: (-x["sessions"], -x["uses"], x["shape"]))
    return results


def _print_table(results: list[dict]) -> None:
    """Print results formatted as a plain-text table."""
    if not results:
        print("No matching shapes found.")
        return

    col_sessions = "Sessions"
    col_projects = "Projects"
    col_uses = "Uses"
    col_shape = "Shape"
    col_example = "Example"

    max_sess = max(len(col_sessions), max(len(str(r["sessions"])) for r in results))
    max_proj = max(len(col_projects), max(len(str(r["projects"])) for r in results))
    max_uses = max(len(col_uses), max(len(str(r["uses"])) for r in results))
    max_shape = max(len(col_shape), max(len(r["shape"]) for r in results))

    header = (
        f"{col_sessions:<{max_sess}}  "
        f"{col_projects:<{max_proj}}  "
        f"{col_uses:<{max_uses}}  "
        f"{col_shape:<{max_shape}}  "
        f"{col_example}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        ex = r["example"].replace("\n", " ").replace("\r", "")
        print(
            f"{r['sessions']:<{max_sess}}  "
            f"{r['projects']:<{max_proj}}  "
            f"{r['uses']:<{max_uses}}  "
            f"{r['shape']:<{max_shape}}  "
            f"{ex}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mine recurring bash command shapes from Claude Code transcripts."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".claude/projects",
        help="Path to Claude projects directory (default: ~/.claude/projects)",
    )
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=3,
        help="Minimum distinct sessions required (default: 3)",
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=30,
        help="Only include files modified within this many days (default: 30; 0 = no limit)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Maximum number of shapes to show (default: 20)",
    )
    parser.add_argument(
        "--min-steps",
        type=int,
        default=2,
        help="Minimum steps in a shape (default: 2; one-step commands are rarely worth a tool)",
    )
    parser.add_argument(
        "--include-tools",
        action="store_true",
        help="Keep steps that already call a just recipe or a script",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print output as a JSON list of objects",
    )
    parser.add_argument("--version", action="version", version=f"tool_miner.py {VERSION}")

    args = parser.parse_args(argv)

    if not args.root.exists():
        sys.stderr.write(f"Error: root directory does not exist: {args.root}\n")
        return 2

    results = mine(args.root, args.since_days, include_tools=args.include_tools)
    results = [r for r in results
               if r["sessions"] >= args.min_sessions and steps(r["shape"]) >= args.min_steps]
    if args.top > 0:
        results = results[:args.top]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        _print_table(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
