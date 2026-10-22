#!/usr/bin/env bash
# PreToolUse(Bash) hook (Windows): block `git commit` unless the docs .session-end.yml
# declares mandatory are staged. Checkpoint commits ("chk: ...") are exempt.
#
# The logic now lives in scripts/commit_doc_guard.py, shared with Linux, so both
# hosts gate the same commits: only real `git ... commit` invocations whose repo is
# this one (or a linked worktree of it). Read-only git calls and commits in nested
# independent clones (review/<x>) pass. Policy is read from .session-end.yml.
# No jq needed: the repo venv interpreter parses the payload and emits the decision.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec bash "$ROOT/scripts/commit-doc-guard.sh"
