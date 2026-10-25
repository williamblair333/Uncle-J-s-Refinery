#!/usr/bin/env python3
"""Copy the MCP servers Claude Code runs (user scope, ~/.claude.json) into agy's config.

agy reads ~/.gemini/config/mcp_config.json (`mcpServers`, same shape as Claude's). Only the
keys agy understands are copied (command, args, env for stdio; url, headers for HTTP).
Servers that exist only on the agy side are kept. The write is atomic, mode 0600 (env may
hold API keys), with a .bak of the previous file. Re-run after the stack's MCP
registrations change. SKIP servers are never copied (and removed if an older sync copied
them): `delegate` would let agy call ask_agy, i.e. itself.

Usage: sync_mcp.py [--claude PATH] [--target PATH]
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_CLAUDE = Path.home() / ".claude.json"
DEFAULT_TARGET = Path.home() / ".gemini" / "config" / "mcp_config.json"
KEEP = ("command", "args", "env", "url", "headers")
SKIP = ("delegate",)


def sync(claude: Path, target: Path) -> list:
    """Merge Claude's user-scope servers into target. Returns the synced server names."""
    source = json.loads(Path(claude).read_text(encoding="utf-8")).get("mcpServers", {})
    source = {n: s for n, s in source.items() if n not in SKIP}
    target = Path(target)
    raw = target.read_text(encoding="utf-8").strip() if target.is_file() else ""
    data = json.loads(raw) if raw else {}
    servers = data.setdefault("mcpServers", {})
    for name in SKIP:
        servers.pop(name, None)
    for name, spec in source.items():
        servers[name] = {k: spec[k] for k in KEEP if k in spec and (spec[k] or k == "args")}
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return sorted(source)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--claude", type=Path, default=DEFAULT_CLAUDE)
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = ap.parse_args(argv)
    names = sync(args.claude, args.target)
    print(f"synced {len(names)} server(s) into {args.target}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
