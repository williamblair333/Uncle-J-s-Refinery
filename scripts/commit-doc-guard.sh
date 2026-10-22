#!/usr/bin/env bash
# PreToolUse(Bash) hook: doc gate for `git commit` in this repo. All logic lives in
# commit_doc_guard.py (see its docstring for what it gates and why); this wrapper
# only picks an interpreter that has pyyaml. Fails open: no python, no block.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 2>/dev/null)"
[ -n "$PY" ] || { cat >/dev/null; exit 0; }
exec "$PY" "$ROOT/scripts/commit_doc_guard.py"
