#!/usr/bin/env bash
# wheelhouse — local copies of everything needed to rebuild the stack's venvs with no network.
#
# Bill 2026-11-14: "they might turn something off and then what." A rebuild today needs PyPI,
# GitHub (the munch packages install from git, and uv downloads its Pythons from GitHub) and
# the uv cache. This keeps, per venv: requirements.txt (the exact freeze), every package as a
# wheel (git and file deps built locally), and the Python interpreter it runs on.
#
#   wheelhouse.sh build [venv...]        refresh copies (default: .venv .venv-memweave)
#   wheelhouse.sh verify [venv...]       rebuild each into a temp venv, offline, and check it
#   wheelhouse.sh restore <venv> <dest>  rebuild <venv> at <dest> from the copies, offline
#   wheelhouse.sh cron                   build then verify (the weekly cron job)
#
# Copies live in $WHEELHOUSE_DIR (default state/wheelhouse, gitignored). The previous build is
# kept as <venv>.old until the next one succeeds. Exit 0 only if every venv succeeded.
set -euo pipefail

ROOT="${REFINERY_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HOUSE="${WHEELHOUSE_DIR:-$ROOT/state/wheelhouse}"
DEFAULT_VENVS=(.venv .venv-memweave)
# Installed but not copied, each with its reason. Anything else that can't be fetched fails
# the build, so a dependency going dark is noticed, not skipped.
SKIP=(
  turbovecdb  # mempalace leftover (retired 2026-06), nothing imports it; its GitHub repo is gone
)

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

python_root() {  # .../cpython-3.11.15-linux-x86_64-gnu for a venv
  local py; py="$(readlink -f "$ROOT/$1/bin/python")"
  dirname "$(dirname "$py")"
}

build_one() {
  local name="$1" venv="$ROOT/$1" new pyroot want got skip_re
  [ -x "$venv/bin/python" ] || { log "FAIL $name: no venv at $venv"; return 1; }
  pyroot="$(python_root "$name")"
  new="$HOUSE/$name.new"
  rm -rf "$new"; mkdir -p "$new/wheels"
  skip_re="^($(IFS='|'; echo "${SKIP[*]}"))([ =@]|$)"
  uv pip freeze --quiet --python "$venv/bin/python" | grep -viE "$skip_re" \
    > "$new/requirements.txt" || true
  # pip runs on the venv's own interpreter, so the wheels it builds match that Python.
  # --no-deps: the freeze is already the complete set, and copies must match what is
  # installed even where the live venv's pins conflict (as .venv's protobuf does).
  if ! uvx --quiet --python "$(readlink -f "$venv/bin/python")" pip wheel --quiet --no-deps \
       --disable-pip-version-check -r "$new/requirements.txt" -w "$new/wheels" \
       > "$new/pip.log" 2>&1; then
    log "FAIL $name: pip wheel failed (see $new/pip.log)"; return 1
  fi
  tar -C "$(dirname "$pyroot")" -czf "$new/python.tar.gz" "$(basename "$pyroot")"
  basename "$pyroot" > "$new/python-name"
  want=$(grep -cvE '^[[:space:]]*(#|$)' "$new/requirements.txt")
  got=$(find "$new/wheels" -name '*.whl' | wc -l)
  if [ "$got" -lt "$want" ]; then
    log "FAIL $name: $got wheels for $want requirements"; return 1
  fi
  date -u +%FT%TZ > "$new/built-at"
  rm -rf "$HOUSE/$name.old"
  if [ -d "$HOUSE/$name" ]; then mv "$HOUSE/$name" "$HOUSE/$name.old"; fi
  mv "$new" "$HOUSE/$name"
  log "OK $name: $got wheels, $(du -sh "$HOUSE/$name" | cut -f1), python $(basename "$pyroot")"
}

restore_one() {  # restore <name> <dest>: offline, from the copies only
  local name="$1" dest="$2" src="$HOUSE/$1" pydir pyname
  [ -f "$src/built-at" ] || { log "FAIL $name: no copies in $src (run build)"; return 1; }
  pyname="$(cat "$src/python-name")"
  pydir="${WHEELHOUSE_PYTHON_DIR:-$(uv python dir)}"
  if [ ! -x "$pydir/$pyname/bin/python3" ]; then
    mkdir -p "$pydir"; tar -C "$pydir" -xzf "$src/python.tar.gz"
  fi
  uv venv --quiet --offline --python "$pydir/$pyname/bin/python3" "$dest"
  uv pip install --quiet --offline --no-index --no-deps --python "$dest/bin/python" \
    "$src"/wheels/*.whl
}

names() {  # normalised package names, one per line, sorted
  sed -E 's/[[:space:]]*(==| @ ).*//; s/[-_.]+/-/g' | tr 'A-Z' 'a-z' | grep -v '^$' | sort -u
}

verify_one() {
  local name="$1" tmp rc=0 missing
  tmp="$(mktemp -d)"
  # A private python dir, so the check proves the archived interpreter works, not the live one.
  if WHEELHOUSE_PYTHON_DIR="$tmp/python" restore_one "$name" "$tmp/venv"; then
    missing=$(comm -23 <(names < "$HOUSE/$name/requirements.txt") \
                       <(uv pip freeze --quiet --python "$tmp/venv/bin/python" | names))
    if [ -z "$missing" ]; then
      log "OK verify $name: all $(names < "$HOUSE/$name/requirements.txt" | wc -l) packages rebuilt offline"
    else log "FAIL verify $name: missing after rebuild: $(echo $missing)"; rc=1; fi
  else
    log "FAIL verify $name: offline rebuild failed"; rc=1
  fi
  rm -rf "$tmp"
  return $rc
}

cmd="${1:-build}"; shift || true
case "$cmd" in
  build|verify)
    [ $# -gt 0 ] || set -- "${DEFAULT_VENVS[@]}"
    mkdir -p "$HOUSE"; rc=0
    exec 9>"$HOUSE/.lock"
    flock -n 9 || { log "SKIP $cmd: another wheelhouse run holds $HOUSE/.lock"; exit 1; }
    for v in "$@"; do "${cmd}_one" "$v" || rc=1; done
    exit $rc ;;
  cron)  # weekly: build, then prove the copies rebuild offline
    bash "$0" build && bash "$0" verify ;;
  restore)
    [ $# -eq 2 ] || { echo "usage: $0 restore <venv> <dest>" >&2; exit 2; }
    restore_one "$1" "$2" && log "OK restore $1 -> $2" ;;
  -h|--help) sed -n '2,15p' "$0" ;;
  *) echo "usage: $0 build|verify|restore|cron ..." >&2; exit 2 ;;
esac
