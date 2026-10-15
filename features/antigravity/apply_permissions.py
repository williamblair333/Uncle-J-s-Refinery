#!/usr/bin/env python3
"""Merge features/antigravity/permissions.json into agy's user settings.

agy keeps its own keys in ~/.gemini/antigravity-cli/settings.json (trustedWorkspaces and
others), so the file is merged, never replaced: only the `permissions` key is set. The
write is atomic (tmp + rename, mode 0600) and a .bak of the previous file is kept.
Re-running with unchanged rules does not rewrite the file.

Usage: apply_permissions.py [--settings PATH] [--rules PATH]
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SETTINGS = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"


def apply(settings: Path, rules: dict) -> bool:
    """Set settings['permissions'] = rules. Returns True when the file changed."""
    settings = Path(settings)
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    wanted = {k: list(rules.get(k, [])) for k in ("allow", "deny", "ask")}
    if data.get("permissions") == wanted:
        return False
    settings.parent.mkdir(parents=True, exist_ok=True)
    if settings.is_file():
        shutil.copy2(settings, settings.with_name(settings.name + ".bak"))
    data["permissions"] = wanted
    tmp = settings.with_name(settings.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, settings)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    ap.add_argument("--rules", type=Path, default=HERE / "permissions.json")
    args = ap.parse_args(argv)
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    changed = apply(args.settings, rules)
    print(f"{'updated' if changed else 'unchanged'}: {args.settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
