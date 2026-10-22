#!/usr/bin/env bash
# clean-install-gate.sh — run the real ./install.sh on a machine that has never seen
# this repo (a fresh debian:bookworm-slim container) and check what it registered.
#
# Claude Code isn't in the container, so a `claude` shim on PATH records every call
# (`mcp add`, `mcp remove`, `plugin ...`) and exits 0. The gate then asserts on that
# record plus the venvs, binaries and ~/.claude files install.sh is meant to leave.
# The uv cache is a host volume, so the second run reuses downloaded wheels (the
# "cached wheel set"); network is still required for git deps, uv itself and the
# ONNX model.
#
# Usage:
#   bash scripts/clean-install-gate.sh            # gate HEAD (what a clean clone gets)
#   bash scripts/clean-install-gate.sh --worktree # gate tracked + untracked files as on disk
#   GATE_IMAGE=ubuntu:24.04 bash scripts/clean-install-gate.sh
#
# Last stdout line: GATE: pass (<n> s)  |  GATE: fail — <reasons>
# Full log: state/clean-install-gate.log. Exit 0 pass, 1 fail, 2 could not run.

set -uo pipefail

# ── inside the container ─────────────────────────────────────────────────────
if [[ "${1:-}" == "--inside" ]]; then
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null
    # PRODUCT.md's users already have git, Python 3.11+ and a C toolchain is the
    # documented fallback for the pysqlite3 build; cron supplies `crontab`.
    apt-get install -y -qq python3 git curl ca-certificates jq cron build-essential \
        >/dev/null
    mkdir -p /root/Uncle-J-s-Refinery
    tar -xf /gate/src.tar -C /root/Uncle-J-s-Refinery
    cd /root/Uncle-J-s-Refinery
    git init -q && git -c user.email=gate@local -c user.name=gate add -A \
        && git -c user.email=gate@local -c user.name=gate commit -qm gate

    cat > /usr/local/bin/claude <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >> /gate/claude-calls.log
exit 0
SHIM
    chmod +x /usr/local/bin/claude
    : > /gate/claude-calls.log

    start=$(date +%s)
    set +e
    ./install.sh --non-interactive --skip-optional </dev/null
    rc=$?
    set -e
    echo "INSTALL_RC=$rc INSTALL_SECONDS=$(( $(date +%s) - start ))" > /gate/result

    fails=()
    [[ $rc -eq 0 ]] || fails+=("install.sh exited $rc")
    for s in jcodemunch jdatamunch jdocmunch serena memweave live_preview; do
        grep -qE "^mcp add -s user $s( |$)" /gate/claude-calls.log \
            || fails+=("no 'claude mcp add -s user $s'")
    done
    for b in jcodemunch-mcp jdatamunch-mcp jdocmunch-mcp; do
        [[ -x .venv/bin/$b ]] || fails+=(".venv/bin/$b missing")
    done
    .venv/bin/jcodemunch-mcp --help >/dev/null 2>&1 || fails+=("jcodemunch-mcp --help failed")
    .venv-memweave/bin/python -c "from memweave import MemWeave" 2>/dev/null \
        || fails+=("memweave not importable in .venv-memweave")
    [[ -s /root/.claude/CLAUDE.md ]] || fails+=("~/.claude/CLAUDE.md not installed")
    compgen -G "/root/.claude/skills/*" >/dev/null || fails+=("no skills in ~/.claude/skills")
    [[ -f /root/.claude/settings.json ]] || fails+=("~/.claude/settings.json missing")
    printf '%s\n' "${fails[@]}" > /gate/fails
    # Hand the shared dirs back to the host user so cleanup and the next run work.
    chown -R "${HOST_UID:-0}:${HOST_GID:-0}" /gate /root/.cache/uv 2>/dev/null || true
    exit 0
fi

# ── on the host ──────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="${GATE_IMAGE:-debian:bookworm-slim}"
CACHE="${GATE_CACHE:-$HOME/.cache/uncle-j-install-gate}"
LOG="$REPO_ROOT/state/clean-install-gate.log"

command -v docker >/dev/null && docker info >/dev/null 2>&1 \
    || { echo "GATE: blocked — docker unavailable"; exit 2; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
if [[ "${1:-}" == "--worktree" ]]; then
    (cd "$REPO_ROOT" && git ls-files -co --exclude-standard -z \
        | xargs -0 tar -cf "$work/src.tar" --) \
        || { echo "GATE: blocked — could not pack the worktree"; exit 2; }
else
    git -C "$REPO_ROOT" archive --format=tar -o "$work/src.tar" HEAD \
        || { echo "GATE: blocked — git archive HEAD failed"; exit 2; }
fi
cp "$0" "$work/gate.sh"
mkdir -p "$CACHE/uv" "$(dirname "$LOG")"

echo "clean-install gate: $IMAGE, log $LOG" >&2
docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
    -v "$work:/gate" -v "$CACHE/uv:/root/.cache/uv" "$IMAGE" \
    bash /gate/gate.sh --inside >"$LOG" 2>&1
drc=$?

if [[ ! -f "$work/result" ]]; then
    echo "GATE: fail — container exited $drc before install.sh finished (see $LOG)"
    exit 1
fi
# shellcheck disable=SC1091
source "$work/result"
mapfile -t fails < <(grep -v '^$' "$work/fails" 2>/dev/null)
cp "$work/claude-calls.log" "$REPO_ROOT/state/clean-install-gate-claude-calls.log" 2>/dev/null
if [[ ${#fails[@]} -eq 0 ]]; then
    echo "GATE: pass (${INSTALL_SECONDS} s; target 900 s)"
    exit 0
fi
printf '    - %s\n' "${fails[@]}" >&2
echo "GATE: fail — ${#fails[@]} check(s) (install ${INSTALL_SECONDS} s; see $LOG)"
exit 1
