"""Lint an agy brief before it spends quota: catch instructions agy is not allowed to follow.

Why: 2026-11-01 two agy jobs failed on rules that lived only in a memory note ("agy job briefs:
main checkout, bare commands, nothing outside cwd, read-don't-run checks"). The brief asked agy
to `git checkout -b` (denied), to read a file under ~/.code-index (outside its readable roots)
and to run `.venv/bin/python -m pytest` (not matched by `command(python)`). Each burned a run.

Rules come from features/antigravity/permissions.json, so changing agy's allow list changes the
lint with no code edit:
  * a command the brief tells agy to run ("Run: X", "run `X`") whose prefix is denied, or that no
    allow rule covers;
  * a request to make or switch a git branch (agy works in the main checkout, `git checkout` is denied);
  * an existing path the brief points at outside every read_file(...) root and outside cwd.
Negated instructions ("do not run git", "never touch /x") are not requests.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

PERMISSIONS = Path(__file__).resolve().parents[2] / "features" / "antigravity" / "permissions.json"

_NEG = re.compile(r"\b(?:do\s+not|don['’]?t|never|no|without|avoid|not)\b[^.\n]{0,40}$", re.I)
_RUN = re.compile(r"\b[Rr]un(?:\s+it\s+with|\s+this|\s+the\s+tests?\s+with)?\s*:\s*(.+)$", re.M)
_RUN_TICK = re.compile(r"\b[Rr]un\s+`([^`\n]+)`")
_BRANCH = re.compile(
    r"\b(?:create|make|open|start|work\s+on|switch\s+to|check\s*out|use)\s+(?:a\s+|the\s+)?(?:new\s+)?"
    r"(?:git\s+|feature\s+)?branch\b|\bgit\s+(?:checkout|switch)\s+-[bc]\b|\bnew\s+(?:git\s+)?branch\s+`",
    re.I)
_PATH = re.compile(r"(?<![\w/:.])(/(?!/)[^\s'\"`<>|;,)]+|~/[^\s'\"`<>|;,)]+)")


def load_rules(path: Path = PERMISSIONS) -> tuple[list[str], list[str], list[str]] | None:
    """(allowed command prefixes, denied command prefixes, readable path roots), or None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    def pick(kind: str, key: str) -> list[str]:
        out = []
        for rule in data.get(kind, []):
            m = re.fullmatch(rf"{key}\((.*)\)", rule)
            if m:
                out.append(m.group(1))
        return out
    return pick("allow", "command"), pick("deny", "command"), pick("allow", "read_file")


def _negated(text: str, start: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    return bool(_NEG.search(text[line_start:start]))


def _segments(cmdline: str) -> list[list[str]]:
    cmdline = cmdline.strip().rstrip(".").strip("`")
    out = []
    for part in re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmdline):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and re.fullmatch(r"\w+=\S*", words[0]):  # FOO=1 cmd
            words = words[1:]
        if words:
            out.append(words)
    return out


def _covered(words: list[str], prefixes: list[str]) -> str | None:
    joined = " ".join(words)
    for p in sorted(prefixes, key=len, reverse=True):
        if joined == p or joined.startswith(p + " "):
            return p
    return None


def run_requests(prompt: str) -> list[str]:
    found = []
    for rx in (_RUN, _RUN_TICK):
        for m in rx.finditer(prompt):
            if not _negated(prompt, m.start()):
                found.append(m.group(1))
    return found


_WORD = re.compile(r"[a-z0-9']+")


def echoed_runs(prompt: str, text: str, n: int = 8) -> list[str]:
    """Runs of n or more words that appear in both the brief and agy's new text.

    Why: 2026-11-06 agy pasted brief phrases ("do NOT make the client indemnify the contractor")
    into contract drafts. A brief that lists exact phrases to check for rewards copying them.
    Each run is reported once, at its longest.
    """
    p, t = _WORD.findall(prompt.lower()), _WORD.findall(text.lower())
    if len(p) < n or len(t) < n:
        return []
    grams = {tuple(p[i:i + n]) for i in range(len(p) - n + 1)}
    runs, i = [], 0
    while i <= len(t) - n:
        if tuple(t[i:i + n]) in grams:
            j = i + n
            while j < len(t) and tuple(t[j - n + 1:j + 1]) in grams:
                j += 1
            runs.append(" ".join(t[i:j]))
            i = j
        else:
            i += 1
    return runs


def lint(prompt: str, cwd: str, rules=None) -> list[str]:
    """Problems with the brief, each naming the rule and the fix. Empty means send it."""
    problems: list[str] = []
    rules = load_rules() if rules is None else rules
    if rules is not None:
        allow, deny, _ = rules
        for req in run_requests(prompt):
            for words in _segments(req):
                cmd = " ".join(words)
                if words[0].startswith((".venv/", "./.venv/")) or "/bin/" in words[0]:
                    problems.append(f"run `{cmd}`: agy's allow rules match bare commands only "
                                    f"(`python3 -m pytest`, `pytest`), not {words[0]}")
                elif d := _covered(words, deny):
                    problems.append(f"run `{cmd}`: `{d}` is denied to agy; run it yourself after")
                elif not _covered(words, allow):
                    problems.append(f"run `{cmd}`: no allow rule covers `{words[0]}`; have agy read "
                                    "the check and run it yourself")
    for m in _BRANCH.finditer(prompt):
        if not _negated(prompt, m.start()):
            problems.append(f"'{m.group(0)}': agy works in the main checkout and `git checkout` is "
                            "denied; make the branch yourself before or after")
            break
    roots = [os.path.abspath(cwd)] + [r.rstrip("/") for r in (rules[2] if rules else [])]
    seen = set()
    for m in _PATH.finditer(prompt):
        raw = m.group(1).rstrip(".:!?")
        p = os.path.abspath(os.path.expanduser(raw))
        if p in seen or _negated(prompt, m.start()):
            continue
        seen.add(p)
        if not os.path.exists(p):
            continue  # a path that doesn't exist is description, not a read target
        if p.count("/") < 2:
            continue  # "a fake /proc", "/run": a bare top-level dir is description, never the file to read
        if any(p == r or p.startswith(r + "/") for r in roots):
            continue
        problems.append(f"{raw}: outside agy's readable roots ({', '.join(roots)}); paste the "
                        "needed lines into the brief instead")
    return problems
