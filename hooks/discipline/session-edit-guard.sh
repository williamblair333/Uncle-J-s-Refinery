#!/usr/bin/env bash
# PreToolUse guard on Edit|Write|MultiEdit|NotebookEdit: refuses an edit into a checkout that is
# not this session's own while another live Claude session works there. Logic, override and the
# session-discovery details live in scripts/session_edit_guard.py.
#
# Failure posture: the settings entry is `bash <this> || exit 1`. A deny is JSON on stdout with
# exit 0; any other outcome becomes exit 1, which Claude Code shows without blocking.
# Recovery: delete the PreToolUse entry naming session-edit-guard from ~/.claude/settings.json.
# Behaviour is pinned by tests/test_session_edit_guard.py.
set -uo pipefail
SELF=$(readlink -f "${BASH_SOURCE[0]}")
exec python3 "${SELF%/hooks/discipline/*}/scripts/session_edit_guard.py" "$@"
