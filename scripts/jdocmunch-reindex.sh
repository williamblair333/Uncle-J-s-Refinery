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

# ── Local-only repos ──────────────────────────────────────────────────────────
#
# Repos here are indexed with NO summarizer calls and NO embedding calls, so
# nothing in their corpus can leave the machine. index_local defaults to
# use_ai_summaries=True and use_embeddings="auto"; both would reach for whatever
# provider the environment happens to expose, silently, with no log line.
#
# jaredrhod-brain is the Obsidian vault at /opt/proj/jaredrhod/vaults/brain. It
# holds a personal-context note that was deliberately kept out of boot context
# precisely so it is not transmitted to a model provider, plus a frozen archive
# of migrated memory. Summarizing it would defeat both.
#
# Deliberately an allowlist, not a global default: the other nine doc repos are
# ordinary project documentation and keep whatever behaviour they had.
#
# Repos also get per-repo corpus exclusions via LOCAL_ONLY_IGNORE below.
LOCAL_ONLY_REPOS=(
    jaredrhod-brain
)

# Extra gitignore-style patterns applied on top of the prune compensation, keyed
# by repo name. Files matched here never enter the corpus OR the cached raw
# mirror under ~/.doc-index.
#
# Two campaign-forge entries in the vault's frozen migrated-memory snapshot hold
# the same credential in clear text. Indexing copies file bytes into the raw
# mirror, which would put that secret in a second location outside the vault's
# own repo — and the vault is deliberately remote-less. Keep them out entirely.
#
# Counted by inspection on 2026-08-15, not from the vault's own note, which
# listed only the networking file. If you add files to that snapshot, re-check.
declare -A LOCAL_ONLY_IGNORE=(
    [jaredrhod-brain]="12 - Archive/Migrated Memory 2026-08-15/-opt-proj-campaign-forge/project_foundry_networking.md
12 - Archive/Migrated Memory 2026-08-15/-opt-proj-campaign-forge/project_foundry_gm_password.md"
)

# Membership test for the allowlist above.
is_local_only() {
    local candidate=$1 entry
    # The +"..." form keeps `set -u` from aborting the whole run if the allowlist
    # is ever emptied — an empty allowlist means "nothing is forced", not "crash".
    for entry in ${LOCAL_ONLY_REPOS[@]+"${LOCAL_ONLY_REPOS[@]}"}; do
        [[ "$entry" == "$candidate" ]] && return 0
    done
    return 1
}

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
# .summary.json is written by index_local itself alongside the manifest (same
# indexed_at) since the 2026-08 jdocmunch — treating it as a repo named
# "<name>.summary" makes index_local fail with KeyError 'owner'.
SIDECARS = (".related.json", ".terms.json", ".boilerplate.json", ".duplicates.json",
            ".summary.json")


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
#
# The probe runs in Python, not flock. MSYS/Git Bash ships no flock (see the LOCK
# block above), and the old `flock -n 8 8>>"$lockfile"` form failed CLOSED here:
# `command not found` is non-zero, so the guard took its "held" branch for every
# repo whose lockfile merely EXISTS. jdocmunch's writer opens that file with
# O_CREAT on every index write and never removes it, so once a repo had been
# indexed once the file was permanent — and this guard then skipped that repo on
# every run, forever, while the script still logged Done and exited 0.
#
# The probe deliberately mirrors the writer it guards, jdocmunch_mcp's
# storage/doc_store.py::_index_write_lock: fcntl.flock on POSIX, and on Windows
# msvcrt.locking of one byte at offset 0. Matching the primitive AND the offset
# is what makes the answer meaningful — a Windows byte-range lock is mandatory,
# so a lock held at byte 0 cannot probe as free. Hence the explicit seek(0).
#
# When neither primitive is importable the probe fails OPEN and says so: a guard
# that cannot evaluate must not silently disable the job it guards. Runs racing
# ourselves are already covered by the mkdir lock above.
#
# Probe exit codes: 0 = held, 1 = free, 2 = cannot determine.
repo_locked() {
    local lockfile="$IDX/$1.json.lock"
    [[ -f "$lockfile" ]] || return 1

    "$PY" - "$lockfile" 2>>"$LOG" <<'PY_EOF'
import os, sys

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

if fcntl is None and msvcrt is None:
    sys.exit(2)

try:
    fd = os.open(sys.argv[1], os.O_RDWR)
except OSError:
    sys.exit(2)

try:
    os.lseek(fd, 0, os.SEEK_SET)
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit(0)
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            sys.exit(0)
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    sys.exit(1)
finally:
    os.close(fd)
PY_EOF

    local rc=$?
    case "$rc" in
        0) return 0 ;;
        1) return 1 ;;
        *) log "WARN    $1 — lock probe unusable (rc=$rc); proceeding without the guard"
           return 1 ;;
    esac
}

# Run one repo's index refresh.
#
# Not `jdocmunch-mcp index-local`, because that CLI exposes no way to pass
# ignore patterns and jdocmunch's own directory pruning is broken for top-level
# dot-directories. In jdocmunch_mcp/tools/index_local.py the prune test is
#
#     _should_skip(f"{dir_rel}/{d}/".lstrip("./"))
#
# and at the repo root dir_rel is ".", so the argument is "./.venv-memweave/".
# str.lstrip takes a CHARACTER SET, not a prefix — it strips every leading "."
# and "/" — so the string becomes "venv-memweave/" and no longer matches the
# ".venv-memweave/" pattern that was supposed to exclude it. Every top-level
# dot-directory therefore leaks into the corpus. ".venv/" survives only by
# coincidence, because the mangled "venv/" happens to match a separate entry in
# jdocmunch's SKIP_PATTERNS; ".venv-memweave/", ".git/" and ".pytest_cache/" do
# not, and this repo's index grew from 104 documents to 357 — most of them
# numpy and onnx files out of the memweave virtualenv — as a result.
#
# So compute the compensating patterns ourselves and pass them through the
# Python API. For each top-level dot-directory that SHOULD have been excluded
# but is not, emit the de-dotted, root-anchored form ("/venv-memweave/") that
# does match post-mangling. Deriving them per-root keeps this generic across
# the repos this script manages and cannot over-exclude a nested directory.
#
# Delete this whole shim once upstream fixes the lstrip — the plain CLI call is
# the fallback below and stays correct either way.
run_index_local() {
    local root=$1 name=$2
    local local_only=0 extra_ignore=""

    # See LOCAL_ONLY_REPOS at the top of this file for why these two are forced
    # off rather than left to index_local's defaults.
    if is_local_only "$name"; then
        local_only=1
        extra_ignore="${LOCAL_ONLY_IGNORE[$name]:-}"
    fi

    "$PY" - "$root" "$name" "$local_only" "$extra_ignore" >>"$LOG" 2>&1 <<'PY_EOF'
import contextlib
import json
import sys
from pathlib import Path

try:
    from jdocmunch_mcp.tools.index_local import index_local
except ImportError as exc:
    print(f"jdocmunch python api unavailable ({exc})", file=sys.stderr)
    sys.exit(3)

root, name = Path(sys.argv[1]).resolve(), sys.argv[2]
local_only = sys.argv[3] == "1"
# One pattern per line; blank lines dropped so an empty argument is simply "none".
forced_ignore = [ln for ln in sys.argv[4].splitlines() if ln.strip()]

patterns = []
try:
    from jdocmunch_mcp.tools.index_local import _load_gitignore, _should_skip

    spec = _load_gitignore(root)

    def excluded(candidate):
        return _should_skip(candidate) or bool(spec and spec.match_file(candidate))

    for child in root.iterdir():
        if not child.is_dir() or not child.name.startswith("."):
            continue
        correct = f"{child.name}/"
        mangled = f"./{correct}".lstrip("./")
        if excluded(correct) and not excluded(mangled):
            patterns.append(f"/{mangled}")
except Exception as exc:  # private helpers moved or renamed upstream
    print(f"prune compensation unavailable ({exc}) — indexing unpatched",
          file=sys.stderr)

if patterns:
    print(f"prune compensation: {' '.join(patterns)}", file=sys.stderr)

# Forced exclusions come last so they apply even when the prune-compensation
# block above raised and left `patterns` empty.
for pattern in forced_ignore:
    if pattern not in patterns:
        patterns.append(pattern)

# State the privacy posture on every run. "reindexed=1" alone cannot tell you
# whether a corpus was summarized by a remote provider; this line can.
if local_only:
    print(f"mode: local-only (no summarizer, no embeddings) — {name}", file=sys.stderr)
    if forced_ignore:
        print(f"forced exclusions: {' | '.join(forced_ignore)}", file=sys.stderr)
else:
    print(f"mode: default (summaries/embeddings per environment) — {name}", file=sys.stderr)

kwargs = {}
if local_only:
    kwargs["use_ai_summaries"] = False
    kwargs["use_embeddings"] = False

# jdoc#65: providers chatter on stdout; keep it off the JSON.
with contextlib.redirect_stdout(sys.stderr):
    result = index_local(path=str(root), name=name,
                         extra_ignore_patterns=patterns or None, **kwargs)

print(json.dumps(result, indent=2))
sys.exit(0 if result.get("success") else 1)
PY_EOF

    local rc=$?
    [[ "$rc" -ne 3 ]] && return "$rc"

    log "WARN    $name — python api unavailable; falling back to the CLI (dot-directories will leak)"
    # The fallback must carry the same posture. Without --no-ai-summaries here, a
    # missing Python API would silently re-enable the summarizer on exactly the
    # repos that must never reach one — the failure path undoing the guarantee
    # the happy path enforces.
    local -a cli_args=(index-local --path "$root" --name "$name")
    if [[ "$local_only" -eq 1 ]]; then
        cli_args+=(--no-ai-summaries --embeddings off)
        [[ -n "$extra_ignore" ]] && while IFS= read -r pattern; do
            [[ -n "$pattern" ]] && cli_args+=(--extra-ignore-pattern "$pattern")
        done <<<"$extra_ignore"
    fi
    "$JDOCMUNCH" "${cli_args[@]}" >>"$LOG" 2>&1
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
# Counted separately from `reindexed` so the summary can tell "nothing drifted"
# apart from "everything drifted and every one was skipped" — see the closing
# WARN below.
drifted=0

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
            drifted=$((drifted + 1))
            if repo_locked "$name"; then
                log "skip    $name — index lock held by another process"
                skipped=$((skipped + 1))
                continue
            fi
            log "reindex $name — $reason"
            if run_index_local "$root" "$name"; then
                reindexed=$((reindexed + 1))
            else
                log "ERROR   $name — index-local failed (see above)"
                failed=$((failed + 1))
            fi
            ;;
    esac
done <<<"$PLAN"

log "Done. drifted=$drifted reindexed=$reindexed skipped=$skipped failed=$failed"

# "reindexed=0 failed=0" is the same shape whether nothing needed doing or the
# guard rejected everything that did — and that ambiguity is exactly what let a
# permanently-stuck lock guard read as healthy for the life of the Windows port.
# Name the difference out loud. Not an exit-code failure: a serve process holding
# the lock during an interactive session is legitimate and would otherwise alarm
# every night.
if [[ "$drifted" -gt 0 && "$reindexed" -eq 0 && "$failed" -eq 0 ]]; then
    log "WARN: ${drifted} repo(s) drifted but none were reindexed — all skipped by the lock guard."
    log "WARN: if this repeats nightly the index is silently frozen; check for a stuck lock in $IDX"
fi

if [[ "$schema_error" -eq 1 ]]; then
    log "ERROR: manifest schema changed — this script needs updating for the new index_version."
    exit 2
fi
[[ "$failed" -gt 0 ]] && exit 1
exit 0
