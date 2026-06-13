#!/usr/bin/env bash
# build-vendored-pysqlite3.sh — build the pysqlite3 wheel against SQLite 3.51.3 ONCE,
# vendored into the repo so `uv sync` stops reverting to the PyPI 3.51.1 wheel.
#
# WHY: SQLite <3.51.3 carries a WAL-reset data-race bug (present since 3.7.0, 2010).
# The PyPI pysqlite3 wheel bundles 3.51.1 — still affected. install.sh §2b builds
# 3.51.3 from source into the venv, but a bare `uv sync` reinstalls the PyPI wheel
# and silently reintroduces the bug. Vendoring a path-pinned 3.51.3 wheel (referenced
# from pyproject.toml [tool.uv.sources]) makes `uv sync` install the FIXED wheel.
#
# This compiles C — it is on the agent Bash deny-list, so run it yourself:
#   ! bash scripts/build-vendored-pysqlite3.sh
#
# After it succeeds, the printed [tool.uv.sources] pin is wired into pyproject.toml
# (separate, pre-mortem'd step), then `uv lock` + `uv sync` + a sqlite_version assert.
set -euo pipefail

PYSQLITE_VERSION="0.6.0"
SQLITE_AMALG_URL="https://www.sqlite.org/2026/sqlite-amalgamation-3510300.zip"
SQLITE_EXPECTED="3.51.3"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$REPO_ROOT/vendor/wheels"
PYBIN="$REPO_ROOT/.venv/bin/python3"

# --- preflight: fail loud and early on a host that can't build -----------------
for tool in curl unzip tar cc; do
    command -v "$tool" >/dev/null 2>&1 || { echo "FATAL: missing build tool: $tool" >&2; exit 1; }
done
[ -x "$PYBIN" ] || { echo "FATAL: venv python not found at $PYBIN (run install.sh first)" >&2; exit 1; }
"$PYBIN" -c "import build" 2>/dev/null || { echo "FATAL: 'build' not in venv — run: uv pip install build --python $PYBIN" >&2; exit 1; }

PYTAG="$("$PYBIN" -c 'import sys;print(f"cp{sys.version_info.major}{sys.version_info.minor}")')"
echo "==> building pysqlite3 $PYSQLITE_VERSION (SQLite $SQLITE_EXPECTED) for $PYTAG"

mkdir -p "$VENDOR_DIR"
TMP_SRC="$(mktemp -d)"
trap 'rm -rf "$TMP_SRC"' EXIT

# --- fetch the SQLite 3.51.3 amalgamation (the fix) ----------------------------
echo "==> fetching SQLite amalgamation"
curl -sSL --fail "$SQLITE_AMALG_URL" -o "$TMP_SRC/amalg.zip"
unzip -j "$TMP_SRC/amalg.zip" "*/sqlite3.c" "*/sqlite3.h" -d "$TMP_SRC/"

# --- fetch the pinned pysqlite3 sdist (curl+python, no uv-subcommand coupling) --
echo "==> fetching pysqlite3 $PYSQLITE_VERSION sdist"
_SDIST_URL="$(curl -sSL --fail "https://pypi.org/pypi/pysqlite3/$PYSQLITE_VERSION/json" \
    | python3 -c "import sys,json;print(next(u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'))")"
curl -sSL --fail "$_SDIST_URL" -o "$TMP_SRC/pysqlite3.tar.gz"
tar xz -C "$TMP_SRC" -f "$TMP_SRC/pysqlite3.tar.gz"
SRC_DIR="$TMP_SRC/pysqlite3-$PYSQLITE_VERSION"
cp "$TMP_SRC/sqlite3.c" "$TMP_SRC/sqlite3.h" "$SRC_DIR/"

# --- build the wheel (statically links the 3.51.3 amalgamation) ----------------
echo "==> building wheel"
( cd "$SRC_DIR" && "$PYBIN" -m build --wheel --outdir "$VENDOR_DIR" )

WHEEL="$(ls -t "$VENDOR_DIR"/pysqlite3-"$PYSQLITE_VERSION"-*.whl | head -1)"
[ -f "$WHEEL" ] || { echo "FATAL: no wheel produced in $VENDOR_DIR" >&2; exit 1; }

# --- verify the built wheel actually carries 3.51.3 ----------------------------
echo "==> verifying built wheel reports SQLite $SQLITE_EXPECTED"
VTMP="$(mktemp -d)"; trap 'rm -rf "$TMP_SRC" "$VTMP"' EXIT
"$PYBIN" -m venv "$VTMP/v"
"$VTMP/v/bin/pip" install --quiet "$WHEEL"
GOT="$("$VTMP/v/bin/python" -c 'import pysqlite3;print(pysqlite3.sqlite_version)')"
if [ "$GOT" != "$SQLITE_EXPECTED" ]; then
    echo "FATAL: built wheel reports SQLite $GOT, expected $SQLITE_EXPECTED — NOT vendoring" >&2
    rm -f "$WHEEL"
    exit 1
fi

REL="${WHEEL#"$REPO_ROOT"/}"
echo
echo "✅ vendored wheel verified: $REL  (SQLite $GOT)"
echo
echo "NEXT (separate pre-mortem'd step — do not hand-edit blindly):"
echo "  Add to pyproject.toml:"
echo "    [tool.uv.sources]"
echo "    pysqlite3 = { path = \"$REL\" }"
echo "  Then: uv lock && uv sync --inexact"
echo "  Then assert: .venv/bin/python -c \"import sqlite3;assert sqlite3.sqlite_version=='$SQLITE_EXPECTED'\""
