#!/usr/bin/env python
"""Export Claude session transcripts (~/.claude/projects/<project>/*.jsonl) to
per-session markdown for memweave to index.

Keeps the *conversation* — human prompts + assistant prose — and drops the
mechanical traffic (tool_use / tool_result / thinking blocks, metadata event
types) plus injected <system-reminder> spans. That noise is exactly what made
the old mempalace transcript-mining near-duplicate garbage (recall ~0); memweave
indexes the cleaned signal instead.

Pure functions (extract_text / strip_system_reminders / iter_turns /
render_markdown) are stdlib-only and unit-tested. I/O is in export_project / main.

Usage (bounded slice first — prove on real data before the full load):
  .venv-memweave/bin/python scripts/memweave/export_transcripts.py \
      --project -opt-proj-Uncle-J-s-Refinery --limit 30
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path(os.path.expanduser("~/.claude/projects"))
# NB: must NOT live under a dir literally named ".memweave" — memweave's
# list_memory_files() skips any path with ".memweave" in its parts (its internal
# index dir), which would exclude every memory file. Hence ~/.uncle-j-memory.
DEFAULT_WORKSPACE = Path(os.path.expanduser("~/.uncle-j-memory"))

_SYS_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)

# When a skill is invoked, the harness injects the skill's full body as a
# user-role turn whose first line is this literal prefix. It's harness traffic,
# not conversation — and stale/superseded skill copies (e.g. an old skill that
# still referenced mempalace) otherwise flood prior-art search with near-dup
# noise, the same failure mode that tanked the old mempalace mining. Drop it like
# a system-reminder. NB: this is a harness convention, not a stable API — if a
# future Claude Code release rewords the header, this filter quietly no-ops back
# to today's behavior (a guard test pins the keep-real-prose side).
_SKILL_BODY_PREFIX = "Base directory for this skill:"


def is_skill_body(text: str) -> bool:
    """True when a turn's text is a harness skill-body injection, not conversation."""
    return text.lstrip().startswith(_SKILL_BODY_PREFIX)


def strip_system_reminders(text: str) -> str:
    """Remove injected <system-reminder>…</system-reminder> spans (harness context,
    not conversation). Collapses the whitespace they leave behind."""
    cleaned = _SYS_REMINDER_RE.sub("", text)
    # Tidy up blank-line runs left by removed spans.
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def extract_text(content) -> str:
    """Human-readable text from a message 'content'. str → the string; list → only
    'text' blocks joined (drops thinking / tool_use / tool_result / images).
    System-reminder spans are stripped. Returns '' when nothing visible remains."""
    if isinstance(content, str):
        return strip_system_reminders(content)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = strip_system_reminders(block.get("text") or "")
                if t:
                    parts.append(t)
        return "\n\n".join(parts)
    return ""


def iter_turns(lines) -> list[tuple[str, str]]:
    """Parse jsonl transcript lines → [(role, text)] for user/assistant messages
    that carry real text. Skips metadata event types, malformed lines, and turns
    whose only content was tool traffic, a system-reminder, or a skill-body
    injection."""
    turns: list[tuple[str, str]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        msg = d.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = extract_text(msg.get("content"))
        if not text:
            continue
        if role == "user" and is_skill_body(text):
            continue
        turns.append((role, text))
    return turns


def render_markdown(session_id, turns, *, project=None, date_iso=None) -> str:
    """Render turns as a markdown memory doc. Empty turns → '' (caller skips)."""
    if not turns:
        return ""
    head = [f"# Session {session_id}"]
    meta = []
    if project:
        meta.append(f"project: {project}")
    if date_iso:
        meta.append(f"date: {date_iso}")
    if meta:
        head.append("_" + " · ".join(meta) + "_")
    body = []
    for role, text in turns:
        label = "User" if role == "user" else "Assistant"
        body.append(f"## {label}\n\n{text}")
    return "\n\n".join(head) + "\n\n" + "\n\n".join(body) + "\n"


def export_project(project, *, projects_root=PROJECTS_ROOT, out_workspace=DEFAULT_WORKSPACE,
                   limit=None, min_chars=200):
    """Export one project's transcripts (newest first) to <out_workspace>/memory/*.md.

    Returns (written, skipped_small, skipped_empty). Idempotent: overwrites the
    per-session file each run; memweave's index() then re-embeds only changed files.
    """
    proj_dir = Path(projects_root).expanduser() / project
    if not proj_dir.is_dir():
        raise FileNotFoundError(f"project transcript dir not found: {proj_dir}")
    transcripts = sorted(proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        transcripts = transcripts[:limit]

    mem_dir = Path(out_workspace).expanduser() / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)

    written = skipped_small = skipped_empty = 0
    for tp in transcripts:
        turns = iter_turns(tp.read_text(errors="replace").splitlines())
        date_iso = datetime.fromtimestamp(tp.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
        md = render_markdown(tp.stem, turns, project=project, date_iso=date_iso)
        out_path = mem_dir / f"{tp.stem}.md"
        if not md or len(md) < min_chars:
            # Too-small/empty after filtering. Remove any stale .md left by a prior
            # export so a newly-tightened filter (e.g. skill-body stripping that
            # shrinks a session below min_chars) actually sheds the old, larger doc
            # instead of leaving it behind. export stays authoritative over the store.
            out_path.unlink(missing_ok=True)
            if not md:
                skipped_empty += 1
            else:
                skipped_small += 1
            continue
        out_path.write_text(md)
        written += 1
    return written, skipped_small, skipped_empty


def export_all_projects(*, projects_root=PROJECTS_ROOT, out_workspace=DEFAULT_WORKSPACE,
                        limit=None, min_chars=200):
    """Export *every* project under projects_root into one shared store.

    Session ids are globally-unique UUIDs, so the flat <out_workspace>/memory dir
    never collides across projects; each rendered doc carries its `project:` metadata.
    Non-directory entries under the root are skipped. Returns aggregate
    (written, skipped_small, skipped_empty, projects).
    """
    root = Path(projects_root).expanduser()
    written = skipped_small = skipped_empty = projects = 0
    for proj_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        w, s, e = export_project(proj_dir.name, projects_root=root,
                                 out_workspace=out_workspace, limit=limit, min_chars=min_chars)
        written += w
        skipped_small += s
        skipped_empty += e
        projects += 1
    return written, skipped_small, skipped_empty, projects


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="-opt-proj-Uncle-J-s-Refinery",
                    help="project dir name under ~/.claude/projects")
    ap.add_argument("--all-projects", action="store_true",
                    help="export every project under ~/.claude/projects into one shared store "
                         "(cross-project corpus); overrides --project")
    ap.add_argument("--out", default=str(DEFAULT_WORKSPACE),
                    help="memweave workspace dir (markdown lands in <out>/memory)")
    ap.add_argument("--limit", type=int, default=None,
                    help="export only the N most recent transcripts (per project; bounded slice)")
    ap.add_argument("--min-chars", type=int, default=200,
                    help="skip rendered docs shorter than this (trivial sessions)")
    args = ap.parse_args()

    if args.all_projects:
        written, small, empty, projects = export_all_projects(
            out_workspace=args.out, limit=args.limit, min_chars=args.min_chars)
        print(f"export_transcripts: all-projects ({projects} projects) -> "
              f"{Path(args.out).expanduser()}/memory")
    else:
        written, small, empty = export_project(
            args.project, out_workspace=args.out, limit=args.limit, min_chars=args.min_chars)
        print(f"export_transcripts: project={args.project} -> {Path(args.out).expanduser()}/memory")
    print(f"  wrote {written} markdown files; skipped {small} too-small, {empty} empty "
          f"(no conversational text)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
