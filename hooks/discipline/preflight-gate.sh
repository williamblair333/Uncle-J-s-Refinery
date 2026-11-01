#!/usr/bin/env bash
# PreToolUse guard on Bash: runs the current repo's declared preflight checks
# (<repo>/.claude/preflight.toml, only for repos listed in config/preflight-trusted.txt)
# before a matching command. Logic and the config format live in scripts/preflight_gate.py.
#
# Failure posture: the settings entry is `bash <this> || exit 1`. A deny is JSON on stdout
# with exit 0; any other outcome (missing python, a crash) becomes exit 1, which Claude Code
# shows without blocking.
# Recovery: delete the PreToolUse entry naming preflight-gate from ~/.claude/settings.json,
# or drop the repo from config/preflight-trusted.txt.
# Behaviour is pinned by tests/test_preflight_gate.py.
set -uo pipefail
SELF=$(readlink -f "${BASH_SOURCE[0]}")
exec python3 "${SELF%/hooks/discipline/*}/scripts/preflight_gate.py"
