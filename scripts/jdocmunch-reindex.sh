#!/usr/bin/env bash
# Drift-gated jdocmunch index refresh. Safe to run on cron or by hand.
#
# Unlike the jcodemunch equivalent, jdocmunch indexes MANY source roots (9 at time
# of writing), most of them outside this repo. So this script does not take a single
# path: it enumerates the manifests already present in ~/.doc-index/local/ and
# refreshes only the ones whose source has actually moved.
#
# Drift detection, per repo:
#   * git source root      -> current HEAD vs the manifest's recorded head_sha
#   * non-git source root  -> newest file mtime in the tree vs manifest indexed_at
#
# A repo whose source root has vanished is skipped, not fatal — one relocated
# project must not stop the other eight from refreshing.
#
# Exit codes: 0 = all good (including "nothing drifted"), 1 = at least one repo
# failed to reindex, 2 = manifest schema is not the version we know how to read.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
JDOCMUNCH="$PROJ_ROOT/.venv/bin/jdocmunch-mcp"
PY="$PROJ_ROOT/.venv/bin/python"
IDX="$HOME/.doc-index/local"
LOG="$PROJ_ROOT/state/jdocmunch-reindex.log"

# The manifest schema this script knows how to read. If jdocmunch ships a new
# index_version, field names may have moved — and reading a renamed field yields
# empty-vs-empty, which silently looks like "nothing drifted". Fail loud instead.
EXPECTED_INDEX_VERSION=3

mkdir -p "$PROJ_ROOT/state"
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

# Prevent concurrent runs (cron + manual invocation can overlap).
# exec failure (disk full, /tmp not writable) is an error — log and bail rather
# than silently masquerading as a concurrency skip.
# mkdir is atomic everywhere and needs no flock, which MSYS/Git Bash does not ship.
# See scripts/jcodemunch-reindex.sh for why the flock form failed open on Windows.
LOCK="${TMPDIR:-/tmp}/uncle-j-jdocmunch-reindex.lock.d"
# See scripts/jcodemunch-reindex.sh: a killed run leaves the dir behind and the
# EXIT trap never fires, silently skipping every later run.
if [[ -d "$LOCK" ]] && [[ -n "$(find "$LOCK" -maxdepth 0 -mmin +120 2>/dev/null)" ]]; then
    log "Stale lock (>2h) — reclaiming $LOCK"
    rmdir "$LOCK" 2>/dev/null || true
fi
if ! mkdir "$LOCK" 2>/dev/null; then
    if [[ -d "$LOCK" ]]; then
        log "Reindex already running — skipping."
        exit 0
    fi
    log "ERROR: cannot create lock dir $LOCK (disk full or TMPDIR not writable)"
    exit 1
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

if [[ ! -x "$JDOCMUNCH" ]]; then
    log "ERROR: jdocmunch-mcp not found at $JDOCMUNCH"
    exit 1
fi
if [[ ! -d "$IDX" ]]; then
    log "ERROR: doc index not found at $IDX — nothing to refresh"
    exit 1
fi

# Emit one TAB-separated decision line per indexed repo:
#   REINDEX <name> <source_root> <reason>
#   SKIP    <name> <source_root> <reason>
#   SCHEMA  <name> <source_root> <reason>
# Decision logic lives here (rather than in bash) so the JSON parsing and the
# mtime walk stay readable.
plan() {
    "$PY" - "$IDX" "$EXPECTED_INDEX_VERSION" <<'PY_EOF'
import datetime, json, os, pathlib, subprocess, sys

idx = pathlib.Path(sys.argv[1])
expected_version = int(sys.argv[2])

# Sidecar files share the <name>.*.json shape; only <name>.json is the manifest.
SIDECARS = (".related.json", ".terms.json", ".boilerplate.json", ".duplicates.json")


def emit(verdict, name, root, reason):
    print(f"{verdict}\t{name}\t{root}\t{reason}")


def newest_mtime(root):
    """Newest mtime under root, skipping VCS and dependency noise."""
    newest = 0.0
    skip = {".git", "node_modules", "__pycache__", ".venv", ".mypy_cache", ".pytest_cache"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            try:
                m = os.stat(os.path.join(dirpath, fn)).st_mtime
            except OSError:
                continue
            if m > newest:
                newest = m
    return newest


for manifest in sorted(idx.glob("*.json")):
    if any(manifest.name.endswith(s) for s in SIDECARS):
        continue
    name = manifest.name[: -len(".json")]
    try:
        with manifest.open() as fh:
            data = json.load(fh)
    except Exception as exc:
        # An unparseable manifest is exactly the torn-write case; rebuilding is
        # the correct repair, but we have no source_root to rebuild from.
        emit("SKIP", name, "", f"manifest unreadable ({type(exc).__name__}) — run index-local by hand")
        continue

    version = data.get("index_version")
    if version != expected_version:
        emit("SCHEMA", name, "", f"index_version={version!r}, expected {expected_version}")
        continue

    root = data.get("source_root") or ""
    if not root:
        emit("SKIP", name, "", "manifest has no source_root")
        continue
    if not os.path.isdir(root):
        emit("SKIP", name, root, "source root no longer exists")
        continue

    # git root -> compare HEAD against the recorded sha
    git_dir = os.path.join(root, ".git")
    if os.path.exists(git_dir):
        try:
            head = subprocess.run(
                ["git", "-C", root, "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
        except Exception:
            head = ""
        recorded = (data.get("head_sha") or "").strip()
        if head and recorded and head == recorded:
            emit("SKIP", name, root, f"at HEAD {head[:8]}")
        elif head:
            emit("REINDEX", name, root, f"HEAD {head[:8]} != indexed {recorded[:8] or 'none'}")
        else:
            emit("REINDEX", name, root, "cannot read git HEAD — refreshing to be safe")
        continue

    # non-git root -> compare newest file mtime against indexed_at
    indexed_at = data.get("indexed_at") or ""
    try:
        stamp = datetime.datetime.fromisoformat(indexed_at).timestamp()
    except Exception:
        emit("REINDEX", name, root, "indexed_at unreadable — refreshing to be safe")
        continue
    newest = newest_mtime(root)
    if newest > stamp:
        when = datetime.datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M")
        emit("REINDEX", name, root, f"file modified {when} after index {indexed_at[:16]}")
    else:
        emit("SKIP", name, root, f"no changes since {indexed_at[:16]}")
PY_EOF
}

# jdocmunch keeps its own <name>.json.lock. If a serve process or another indexer
# holds it, rewriting the manifest underneath risks a torn read — skip this pass.
repo_locked() {
    local lockfile="$IDX/$1.json.lock"
    [[ -f "$lockfile" ]] || return 1
    if flock -n 8 8>>"$lockfile" 2>/dev/null; then
        exec 8>&-   # acquired => nobody else holds it
        return 1
    fi
    return 0
}

log "Scanning $IDX for drifted doc indexes ..."

PLAN="$(plan)"
if [[ -z "$PLAN" ]]; then
    log "ERROR: no manifests found in $IDX"
    exit 1
fi

schema_error=0
failed=0
reindexed=0
skipped=0

while IFS=$'\t' read -r verdict name root reason; do
    [[ -z "$verdict" ]] && continue
    case "$verdict" in
        SCHEMA)
            log "SCHEMA  $name — $reason"
            schema_error=1
            ;;
        SKIP)
            log "skip    $name — $reason"
            skipped=$((skipped + 1))
            ;;
        REINDEX)
            if repo_locked "$name"; then
                log "skip    $name — index lock held by another process"
                skipped=$((skipped + 1))
                continue
            fi
            log "reindex $name — $reason"
            if "$JDOCMUNCH" index-local --path "$root" --name "$name" >>"$LOG" 2>&1; then
                reindexed=$((reindexed + 1))
            else
                log "ERROR   $name — index-local failed (see above)"
                failed=$((failed + 1))
            fi
            ;;
    esac
done <<<"$PLAN"

log "Done. reindexed=$reindexed skipped=$skipped failed=$failed"

if [[ "$schema_error" -eq 1 ]]; then
    log "ERROR: manifest schema changed — this script needs updating for the new index_version."
    exit 2
fi
[[ "$failed" -gt 0 ]] && exit 1
exit 0
