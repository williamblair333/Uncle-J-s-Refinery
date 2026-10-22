#!/usr/bin/env bash
# Repair upstream claude-guardrails hooks whose grep pattern starts with "--".
#
# full/settings.json ships `grep -qEi "--dangerously-skip-permissions|--bypass-permissions"`.
# grep reads that pattern as an option, prints "unrecognized option" and exits 2, so the
# `if` is false on every Bash call: the escalation block has never fired. Adding `-e`
# makes it a pattern. install-guardrails.sh re-merges the upstream template, so it calls
# this afterwards; refinery-doctor can call it any time. Idempotent; atomic write + backup.
#
# Usage: fix-guardrails-grep.sh [--check]
set -euo pipefail
SETTINGS="${HOME}/.claude/settings.json"
MODE="${1:-fix}"
[[ -f "$SETTINGS" ]] || { echo "    OK  no settings.json — nothing to repair"; exit 0; }

python3 - "$SETTINGS" "$MODE" <<'PYEOF'
import json, os, re, shutil, sys, tempfile
path, mode = sys.argv[1:3]
with open(path) as fh:
    config = json.load(fh)
# grep with a short-flag cluster, then a quoted pattern that begins with "--"
BAD = re.compile(r'(grep\s+-[A-Za-z]+\s+)(\\?"--)')
fixed = 0
for entries in (config.get("hooks") or {}).values():
    for entry in entries:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            new = BAD.sub(r"\1-e \2", cmd)
            if new != cmd:
                fixed += 1
                h["command"] = new
if mode == "--check":
    print(f"    {'X ' if fixed else 'OK'}  {fixed} guardrails grep pattern(s) read as options" if fixed
          else "    OK  guardrails grep patterns are safe")
    sys.exit(1 if fixed else 0)
if not fixed:
    print("    OK  guardrails grep patterns already safe")
    sys.exit(0)
shutil.copy2(path, path + ".bak")
with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(path), delete=False) as tmp:
    json.dump(config, tmp, indent=2)
    tmp.write("\n")
    tmp.flush()
    os.fsync(tmp.fileno())
    name = tmp.name
os.replace(name, path)
print(f"    OK  repaired {fixed} guardrails grep pattern(s) in {path}")
PYEOF
