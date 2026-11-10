#!/usr/bin/env bash
# install.sh - register the tool-recipes SessionStart hook and write the global justfile
#
# - Registers hooks/session-start.sh in ~/.claude/settings.json, keyed on a marker so
#   a re-run changes nothing. Backs settings.json up first and writes it atomically.
# - Runs `tools.py sync` once, so `just -g <project> <recipe>` works straight away.
#
# Usage: install.sh [--check | --uninstall | --dry-run]
#   --check      report whether the hook is registered and the global justfile current
#   --dry-run    say what would change, change nothing
#   --uninstall  remove the hook (the global justfile is left; delete it by hand)
# Docs: docs/TOOLS-STANDARD.md
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
SETTINGS="${HOME}/.claude/settings.json"
MARKER="tool-recipes:session-start"
ACTION="install"

case "${1:-}" in
    --check)     ACTION="check" ;;
    --dry-run)   ACTION="dry-run" ;;
    --uninstall) ACTION="uninstall" ;;
    -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    "")          ;;
    *)           echo "install.sh: unknown option $1 (see --help)" >&2; exit 2 ;;
esac

if [[ "$ACTION" == "install" ]]; then
    chmod +x "$HERE/hooks/session-start.sh" "$REPO_ROOT/scripts/tools.py" \
        "$REPO_ROOT/scripts/inbox.py" "$REPO_ROOT/scripts/tool_miner.py" 2>/dev/null || true
fi

rc=0
python3 - "$SETTINGS" "$ACTION" "$HERE/hooks/session-start.sh" "$MARKER" <<'PYEOF' || rc=$?
import copy, json, os, shutil, sys, tempfile

settings_path, action, hook, marker = sys.argv[1:5]
try:
    with open(settings_path) as fh:
        config = json.load(fh)
except FileNotFoundError:
    config = {}
except json.JSONDecodeError as exc:
    print(f"    !!  {settings_path} is not valid JSON ({exc}); refusing to touch it")
    raise SystemExit(1)

command = f"[ -x {hook} ] || exit 0; {hook}  # {marker}"
before = copy.deepcopy(config)
hooks = config.setdefault("hooks", {})
entries = hooks.get("SessionStart", [])

# Match our hook inside each entry, not whole entries: an entry can hold other
# hooks too, and those must survive install and uninstall.
ours, kept = [], []
for entry in entries:
    inner = entry.get("hooks", [])
    mine = [h for h in inner if marker in str(h.get("command", ""))]
    ours += mine
    rest = [h for h in inner if h not in mine]
    if rest or not mine:
        kept.append({**entry, "hooks": rest} if mine else entry)
current = len(ours) == 1 and ours[0].get("command") == command

if action == "check":
    print(f"    {'OK' if current else '!!'}  SessionStart hook {'registered' if current else 'missing or outdated'}")
    raise SystemExit(0 if current else 1)

if action in ("install", "dry-run") and current:
    print("    OK  SessionStart hook already registered")
    raise SystemExit(0)
if action == "uninstall" and not ours:
    print("    OK  SessionStart hook not registered; nothing to remove")
    raise SystemExit(0)
if action == "dry-run":
    print(f"    would {'update' if ours else 'add'} the SessionStart hook in {settings_path}")
    raise SystemExit(0)

if action == "install":
    kept.append({"hooks": [{"type": "command", "command": command}]})
if kept:
    hooks["SessionStart"] = kept
else:
    hooks.pop("SessionStart", None)
if not hooks:
    config.pop("hooks", None)
if config == before:
    raise SystemExit(0)

os.makedirs(os.path.dirname(settings_path), exist_ok=True)
if os.path.exists(settings_path):
    shutil.copy2(settings_path, settings_path + ".bak")  # only when something changes
with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(settings_path), delete=False) as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write("\n")
    tmp.flush()
    os.fsync(tmp.fileno())
os.replace(tmp.name, settings_path)
print(f"    OK  SessionStart hook {action}ed in {settings_path}")
PYEOF
[[ $rc -ne 0 && "$ACTION" != "check" ]] && exit "$rc"

case "$ACTION" in
    install)   python3 "$REPO_ROOT/scripts/tools.py" sync || echo "    !!  tools.py sync failed; run: just tools sync" >&2 ;;
    check)     python3 "$REPO_ROOT/scripts/tools.py" sync --check || rc=1; exit "$rc" ;;
    dry-run)   python3 "$REPO_ROOT/scripts/tools.py" sync --check || echo "    would write the global justfile" ;;
    uninstall) echo "    left the global justfile in place: $(python3 "$REPO_ROOT/scripts/tools.py" sync --check --json 2>/dev/null || true)" ;;
esac
