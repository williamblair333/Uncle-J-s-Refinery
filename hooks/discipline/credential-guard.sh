#!/usr/bin/env bash
# PreToolUse guard on EVERY tool (matcher "*"): denies any tool call that touches a
# system or private credential file, read-only included.
#
# Why: claude-guardrails' Read(~/.ssh/**) deny rules cover only built-in tools; its own
# SETUP.md notes `cat ~/.ssh/id_rsa` through Bash walks around them, and so would any
# MCP tool that takes a path. This hook sees every tool call.
#
# What is inspected (never file CONTENTS, so code that merely mentions .ssh can still
# be written):
#   * Bash: the command text.
#   * every other tool, MCP included: string arguments whose key looks like a path
#     (file_path, path, paths, notebook_path, images, ...; Glob's pattern too).
#
# What is denied (boundary-anchored, case-sensitive):
#   * dirs:   .ssh (all of it: known_hosts and config map the hosts) .gnupg .aws
#             .azure .kube .docker .password-store
#             .config/gcloud .config/gh .local/share/keyrings
#   * files:  .netrc .pgpass .git-credentials .npmrc .pypirc .claude.json
#             .claude/.credentials.json  .env and .env.* (not .example/.sample/
#             .template/.dist/.defaults)  id_rsa/id_dsa/id_ecdsa/id_ed25519[_sk]
#             (not .pub)  *.p12 *.pfx *.jks *.keystore *.kdbx  *.key (path args only)
#   * system: /etc/shadow /etc/gshadow /etc/sudoers(.d) /etc/ssh/ssh_host_*_key
#             (not .pub) /etc/ssl/private /root /proc/*/environ
#
# Failure posture: the settings entry is `bash <this> || exit 1`. A deny is JSON on
# stdout with exit 0; EVERY other outcome (syntax error = 2, missing file = 127, jq
# failure) becomes exit 1, which Claude Code reports without blocking. A broken guard
# fails open and loud — it can never lock every tool, Edit included, out of a session.
#
# Residual risk (accepted, pre-mortem 2026-10-17): text matching cannot see obfuscated
# paths (`D=.ss; cat ~/${D}h/x`, base64, a script that does the read). This stops
# accidental and casual reads; it is not a sandbox.
#
# Recovery if it ever misbehaves: delete the PreToolUse entry whose command names
# credential-guard from ~/.claude/settings.json (or remove the symlink at
# ~/.claude/hooks/discipline/credential-guard.sh; a missing script is a non-blocking 127).
# Behaviour is pinned by tests/test_credential_guard.py.
set -uo pipefail

PROJ_ROOTS="${UNCLE_J_PROJ_ROOT:+$UNCLE_J_PROJ_ROOT }/opt/proj /c/opt/proj"
LOG_ROOT=/opt/proj
for _cand in $PROJ_ROOTS; do
  [ -d "$_cand" ] && { LOG_ROOT="$_cand"; break; }
done
LOG="$LOG_ROOT/Uncle-J-s-Refinery/state/hook-blocks.log"

if ! command -v jq >/dev/null 2>&1; then
  echo "credential-guard: jq not found on PATH — guard inactive for this call" >&2
  exit 1
fi

INPUT=$(cat)
TOOL=$(jq -r '.tool_name // empty' <<<"$INPUT" 2>/dev/null) || exit 1
SESSION_ID=$(jq -r '.session_id // "unknown"' <<<"$INPUT" 2>/dev/null) || SESSION_ID=unknown

PATH_KEYS='^(file_?path|path|paths|notebook_path|file|files|filename|dir|directory|folder|cwd|root|source|target|dest|destination|image|images|doc_path|output_path|out_dir|input|inputs|uri|url|glob|location)$'

if [[ "$TOOL" == "Bash" ]]; then
  CANDS=$(jq -r '.tool_input.command // empty' <<<"$INPUT" 2>/dev/null) || exit 1
else
  CANDS=$(jq -r --arg keys "$PATH_KEYS" --arg tool "$TOOL" '
    (.tool_input // {})
    | [paths(type == "string") as $p
       | {key: ([$p[] | select(type == "string")] | last // ""), val: getpath($p)}]
    | map(select((.key | test($keys; "i")) or (.key == "pattern" and $tool == "Glob")))
    | .[].val' <<<"$INPUT" 2>/dev/null) || exit 1
fi
[[ -z "$CANDS" ]] && exit 0

# B: what may precede a match (not a word char, dot, $ or -), so process.env,
# os.environ and my_id_rsa never match. A: what may follow (not a word char or -).
B='(^|[^A-Za-z0-9_.$-])'
A='([^A-Za-z0-9_-]|$)'
PATTERNS=(
  "${B}\\.(ssh|gnupg|aws|azure|kube|docker|password-store)${A}"
  "${B}\\.config/(gcloud|gh)${A}"
  "${B}\\.local/share/keyrings${A}"
  "${B}\\.claude/\\.credentials\\.json${A}"
  "${B}\\.(netrc|pgpass|git-credentials|npmrc|pypirc|claude\\.json)${A}"
  "${B}\\.env(\\.[A-Za-z0-9_-]+)?${A}"
  "${B}id_(rsa|dsa|ecdsa|ed25519)(_sk)?(\\.pub)?${A}"
  "/etc/(g?shadow-?|sudoers(\\.d)?)${A}"
  "/etc/ssh/ssh_host_[A-Za-z0-9]+_key(\\.pub)?${A}"
  "/etc/ssl/private${A}"
  "${B}/root${A}"
  "/proc/[^/[:space:]]+/environ${A}"
  "${B}[A-Za-z0-9_-]+\\.(p12|pfx|jks|keystore|kdbx)${A}"
)
[[ "$TOOL" != "Bash" ]] && PATTERNS+=("[A-Za-z0-9_-]\\.key$")

allowed_hit() {
  # Public halves and committed templates are not credentials.
  local h="$1"
  [[ "$h" =~ \.pub([^A-Za-z0-9_-]|$) ]] && return 0
  [[ "$h" =~ \.env\.(example|sample|template|dist|defaults)([^A-Za-z0-9_-]|$) ]] && return 0
  return 1
}

HIT=""
while IFS= read -r cand; do
  [[ -z "$cand" ]] && continue
  for re in "${PATTERNS[@]}"; do
    while IFS= read -r h; do
      [[ -z "$h" ]] && continue
      allowed_hit "$h" && continue
      HIT="$h"
      break 3
    done < <(printf '%s\n' "$cand" | command grep -oE -- "$re" 2>/dev/null || true)
  done
done <<< "$CANDS"

[[ -z "$HIT" ]] && exit 0

# Trim the boundary characters the match consumed, for a readable reason and log line.
HIT=$(printf '%s' "$HIT" | sed -E 's/^[^A-Za-z0-9_./~-]+//; s/[^A-Za-z0-9_./~-]+$//')
if [[ -d "${LOG%/*}" ]]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') BLOCKED credential-guard tool=$TOOL match=$(printf '%s' "$HIT" | tr '\n\r\t' ' ' | head -c 120) session=$SESSION_ID" >> "$LOG" 2>/dev/null || true
fi

REASON="Blocked by credential-guard: this $TOOL call touches a credential or system secret file (matched: $HIT).

Every tool is covered, read-only included, by design. Don't work around it with another
tool or an indirect path. If the file is genuinely needed, ask Bill to run the command
himself with \`!\`. Logged to state/hook-blocks.log"

jq -n --arg r "$REASON" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": $r
  }
}' || exit 1
exit 0
