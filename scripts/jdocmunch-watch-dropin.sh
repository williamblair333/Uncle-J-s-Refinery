#!/usr/bin/env bash
# jdocmunch-watch-dropin.sh — keep the jdocmunch doc watcher's summaries off.
#
# Workaround for upstream jdocmunch-mcp#120: `jdocmunch-mcp watch-install` rewrites
# ~/.config/systemd/user/jdocmunch-watch.service on every run with no way to pass
# flags, and watch.py defaults use_ai_summaries=True. A systemd drop-in survives the
# rewrite (the installer never touches .service.d/), so the flag lives there.
#
# Usage:
#   bash scripts/jdocmunch-watch-dropin.sh check     # exit 0 ok / not applicable, 1 missing
#   bash scripts/jdocmunch-watch-dropin.sh install   # write the drop-in if missing (idempotent)
#
# Last stdout line: no-unit | present | missing | installed
#
# "present" means some ExecStart= in the unit or any drop-in already carries
# --no-ai-summaries — a hand-written override.conf, or upstream passthrough once #120
# lands. Nothing is written then, so a host's own drop-in is never replaced.
#
# install writes its own file (uncle-j-no-ai-summaries.conf), never override.conf, so
# `systemctl --user edit` content is left alone. It sorts after override.conf, so its
# ExecStart= reset wins. After writing it runs daemon-reload and try-restart (restarts
# only a running watcher). Set JDOCMUNCH_DROPIN_NO_RELOAD=1 to skip both.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-check}"

UNIT_NAME="jdocmunch-watch.service"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$UNIT_NAME"
DROPIN_DIR="$UNIT.d"
DROPIN="$DROPIN_DIR/uncle-j-no-ai-summaries.conf"
FLAG="--no-ai-summaries"

case "$MODE" in
    check|install) ;;
    *) printf 'usage: %s check|install\n' "$0" >&2; exit 2 ;;
esac

# No watcher unit on this machine: not applicable. The drop-in is created alongside
# the unit, never ahead of it — a drop-in for a unit that doesn't exist does nothing.
if [[ ! -f "$UNIT" ]]; then
    echo "no-unit"
    exit 0
fi

has_flag() {
    local f
    for f in "$UNIT" "$DROPIN_DIR"/*.conf; do
        [[ -f "$f" ]] || continue
        grep -E '^[[:space:]]*ExecStart=' "$f" | grep -qF -- "$FLAG" && return 0
    done
    return 1
}

if has_flag; then
    echo "present"
    exit 0
fi

if [[ "$MODE" == check ]]; then
    echo "missing"
    exit 1
fi

# Reuse the unit's own command line (watch-install writes sys.executable there), so
# the repo carries no host path. Fallback only if the unit has no usable ExecStart.
exec_start="$(grep -E '^[[:space:]]*ExecStart=.+' "$UNIT" | tail -n 1 | sed -E 's/^[[:space:]]*ExecStart=//')"
if [[ -z "$exec_start" ]]; then
    exec_start="$STACK_ROOT/.venv/bin/python3 -m jdocmunch_mcp watch"
fi
exec_start="$exec_start $FLAG"

mkdir -p "$DROPIN_DIR"
tmp="$(mktemp "$DROPIN.XXXXXX")" || { echo "mktemp failed" >&2; exit 2; }
cat > "$tmp" <<EOF
# Written by Uncle J's Refinery: scripts/jdocmunch-watch-dropin.sh
# (install-reliability.sh, refinery-doctor.sh --fix). Re-run either to restore it.
#
# Why a drop-in: jdocmunch-mcp watch-install rewrites $UNIT_NAME on every run and
# takes no flags (upstream jdocmunch-mcp#120). It never touches .service.d/.
#
# What it prevents: watch.py defaults use_ai_summaries=True. The watcher re-indexes
# every locally-indexed doc repo on any change, including corpora kept local-only
# (scripts/jdocmunch-reindex.sh LOCAL_ONLY_REPOS covers the cron path). With an
# ANTHROPIC_API_KEY or GOOGLE_API_KEY reachable, every edited section would go to a
# remote summarizer with no log line.
#
# WATCHFILES_IGNORE_PERMISSION_DENIED: awatch() recurses each repo's whole tree; an
# unreadable dir (a container's postgres volume) otherwise raises PermissionError on
# every rediscover pass.
#
# Verify: systemctl --user show $UNIT_NAME -p ExecStart
# Revert: rm "$DROPIN" && systemctl --user daemon-reload && systemctl --user restart $UNIT_NAME

[Service]
Environment=WATCHFILES_IGNORE_PERMISSION_DENIED=1
ExecStart=
ExecStart=$exec_start
EOF
mv "$tmp" "$DROPIN"

if [[ "${JDOCMUNCH_DROPIN_NO_RELOAD:-0}" != 1 ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 \
        && systemctl --user try-restart "$UNIT_NAME" >/dev/null 2>&1 \
        || echo "systemctl --user reload/restart failed — run: systemctl --user daemon-reload && systemctl --user restart $UNIT_NAME" >&2
fi
echo "installed"
exit 0
