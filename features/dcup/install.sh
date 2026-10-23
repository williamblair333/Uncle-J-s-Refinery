#!/usr/bin/env bash
# dcup — install / uninstall / check
#
# - Creates the port registry dir (lockfile + exceptions file) if missing. dcup picks the
#   dir: $DCUP_REGISTRY_DIR, else /opt/lib/docker-port-registry if it exists, else
#   ${XDG_DATA_HOME:-~/.local/share}/dcup. An existing ports.db is never touched.
# - Symlinks ~/.local/bin/dcup -> this directory's dcup (a regular file there is left alone).
# - Registers dcup_guard.py as a PreToolUse Bash hook in ~/.claude/settings.json, keyed on
#   a marker so a re-run changes nothing. The path is written at install time, never
#   committed; a `[ -f ] || exit 0` guard makes a moved checkout a no-op, not a blocked Bash.
# - settings.json is written atomically after a .bak copy.
#
# Usage: install.sh [--uninstall | --check]
#   --check prints one word on the last line: installed | missing
# Claude Code reads hooks at startup: restart it after install/uninstall.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${DCUP_SETTINGS:-${HOME}/.claude/settings.json}"
BIN_DIR="${DCUP_BIN_DIR:-${HOME}/.local/bin}"
MARKER="dcup:guard"

step() { printf '==> %s\n' "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }

registry_dir() {
  if [[ -n "${DCUP_REGISTRY_DIR:-}" ]]; then echo "$DCUP_REGISTRY_DIR"
  elif [[ -d /opt/lib/docker-port-registry ]]; then echo /opt/lib/docker-port-registry
  else echo "${XDG_DATA_HOME:-$HOME/.local/share}/dcup"; fi
}

# hooks <install|uninstall|check>
hooks() {
  python3 - "$SETTINGS" "$1" "$SCRIPT_DIR" "$MARKER" <<'PYEOF'
import json, os, shlex, shutil, sys, tempfile

settings_path, action, script_dir, marker = sys.argv[1:5]
guard = os.path.join(script_dir, "dcup_guard.py")
q = shlex.quote(guard)
command = f"[ -f {q} ] || exit 0; python3 {q}  # {marker}"

try:
    with open(settings_path) as fh:
        config = json.load(fh)
except FileNotFoundError:
    config = {}
except json.JSONDecodeError as exc:
    print(f"    !!  settings.json is not valid JSON ({exc}) — refusing to touch it")
    raise SystemExit(1)

hooks = config.get("hooks") or {}
entries = hooks.get("PreToolUse", [])
mine = [h.get("command", "") for e in entries for h in e.get("hooks", [])
        if marker in h.get("command", "")]

if action == "check":
    print("installed" if mine == [command] else "missing")
    raise SystemExit(0)

if action == "install" and mine == [command]:
    print(f"    OK  hook already registered in {settings_path}")
    raise SystemExit(0)

kept = [e for e in entries
        if not any(marker in h.get("command", "") for h in e.get("hooks", []))]
if action == "install":
    kept.append({"matcher": "Bash", "hooks": [{"type": "command", "command": command}]})
if kept:
    hooks["PreToolUse"] = kept
else:
    hooks.pop("PreToolUse", None)
if hooks:
    config["hooks"] = hooks
else:
    config.pop("hooks", None)

directory = os.path.dirname(settings_path) or "."
os.makedirs(directory, exist_ok=True)
if os.path.exists(settings_path):
    shutil.copy2(settings_path, settings_path + ".bak")
with tempfile.NamedTemporaryFile("w", dir=directory, delete=False) as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write("\n")
    tmp.flush()
    os.fsync(tmp.fileno())
    name = tmp.name
os.replace(name, settings_path)
print(f"    OK  hook {action}ed in {settings_path}")
PYEOF
}

link_state() {
  local link="$BIN_DIR/dcup"
  if [[ -L "$link" && "$(readlink -f "$link")" == "$SCRIPT_DIR/dcup" ]]; then echo ours
  elif [[ -e "$link" || -L "$link" ]]; then echo other
  else echo none; fi
}

case "${1:-}" in
  --check)
    state="$(hooks check)"
    [[ "$(link_state)" == ours ]] || state=missing
    echo "$state"
    exit 0
    ;;
  --uninstall)
    step "Removing dcup guard hook"
    hooks uninstall
    if [[ "$(link_state)" == ours ]]; then rm "$BIN_DIR/dcup"; ok "removed $BIN_DIR/dcup"; fi
    step "Done. The registry ($(registry_dir)) is left alone. Restart Claude Code."
    exit 0
    ;;
  "") ;;
  *) echo "usage: $0 [--uninstall | --check]" >&2; exit 2 ;;
esac

# A worktree is deleted after its PR merges; a symlink or hook pointing into it would
# leave dcup missing from PATH. Install from the main checkout.
if [[ "$SCRIPT_DIR" == */.claude/worktrees/* && -z "${DCUP_ALLOW_WORKTREE:-}" ]]; then
  warn "refusing to install from a worktree ($SCRIPT_DIR) — run the main checkout's copy"
  exit 1
fi

step "Checking prerequisites"
command -v sqlite3 >/dev/null 2>&1 && ok "sqlite3" || warn "sqlite3 missing — dcup can't run (sudo apt-get install sqlite3)"
command -v python3 >/dev/null 2>&1 || { warn "python3 missing — the guard hook needs it"; exit 1; }

step "Port registry"
REG="$(registry_dir)"
if mkdir -p "$REG" 2>/dev/null && touch "$REG/registry.lock" 2>/dev/null; then
  [[ -f "$REG/port-exceptions.toml" ]] || cp "$SCRIPT_DIR/port-exceptions.example.toml" "$REG/port-exceptions.toml"
  ok "$REG ($( [[ -f "$REG/ports.db" ]] && echo 'existing ports.db kept' || echo 'ports.db is created on first dcup up/scan'))"
else
  warn "can't write $REG — set DCUP_REGISTRY_DIR to a writable dir and re-run"
fi

step "Linking dcup"
chmod +x "$SCRIPT_DIR/dcup" "$SCRIPT_DIR/dcup_guard.py" "$SCRIPT_DIR/docker-port-sweeper.sh"
mkdir -p "$BIN_DIR"
case "$(link_state)" in
  ours)  ok "$BIN_DIR/dcup (already linked)" ;;
  none)  ln -s "$SCRIPT_DIR/dcup" "$BIN_DIR/dcup"; ok "$BIN_DIR/dcup -> $SCRIPT_DIR/dcup" ;;
  other)
    if [[ -L "$BIN_DIR/dcup" ]]; then
      ln -sfn "$SCRIPT_DIR/dcup" "$BIN_DIR/dcup"; ok "repointed $BIN_DIR/dcup -> $SCRIPT_DIR/dcup"
    else
      warn "$BIN_DIR/dcup is a regular file — left alone; remove it to use the vendored copy"
    fi
    ;;
esac
found="$(command -v dcup 2>/dev/null || true)"
if [[ -z "$found" ]]; then
  warn "dcup is not on PATH — add $BIN_DIR to PATH"
elif [[ "$(readlink -f "$found")" != "$SCRIPT_DIR/dcup" ]]; then
  warn "PATH finds $found first, not the vendored copy (put $BIN_DIR earlier in PATH)"
fi

step "Registering guard hook"
hooks install

step "Installed. Restart Claude Code to load the hook."
printf '  Registry:  dcup list\n'
printf '  Uninstall: %s/install.sh --uninstall\n' "$SCRIPT_DIR"
