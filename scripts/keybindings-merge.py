#!/usr/bin/env python3
"""Add Alt+V -> chat:imagePaste to ~/.claude/keybindings.json without touching anything else.

Some terminals (Tabby, built on Electron) handle Ctrl+V themselves, so Claude Code never sees
it and image paste does nothing. Alt+V is a second binding; Ctrl+V keeps working.

    keybindings-merge.py check   # prints one state: present | taken | missing | unreadable
    keybindings-merge.py merge   # adds the binding when the state is missing

present    Chat already binds alt+v to chat:imagePaste.
taken      Chat binds alt+v to something else. That's the user's choice; never overwritten.
missing    No alt+v in Chat (or no file). `merge` adds it, keeping every other binding.
unreadable The file isn't valid JSON of the expected shape. Nothing is written.

Exit 0 except for a bad argument (2). The last stdout line is the state (after merge:
`merged` or the unchanged state).
"""
import json
import os
import sys
from pathlib import Path

KEY, ACTION, CONTEXT = "alt+v", "chat:imagePaste", "Chat"
SKELETON = {
    "$schema": "https://www.schemastore.org/claude-code-keybindings.json",
    "$docs": "https://code.claude.com/docs/en/keybindings",
    "bindings": [],
}


def target() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))) / ".claude" / "keybindings.json"


def load(p: Path):
    """(data, state). data is None when the file is unreadable."""
    if not p.exists():
        return json.loads(json.dumps(SKELETON)), "missing"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "unreadable"
    if not isinstance(data, dict) or not isinstance(data.get("bindings", []), list):
        return None, "unreadable"
    data.setdefault("bindings", [])
    for block in data["bindings"]:
        if not isinstance(block, dict) or not isinstance(block.get("bindings", {}), dict):
            return None, "unreadable"
        if block.get("context") == CONTEXT and KEY in block.get("bindings", {}):
            return data, "present" if block["bindings"][KEY] == ACTION else "taken"
    return data, "missing"


def merge(p: Path, data: dict) -> None:
    for block in data["bindings"]:
        if block.get("context") == CONTEXT:
            block.setdefault("bindings", {})[KEY] = ACTION
            break
    else:
        data["bindings"].append({"context": CONTEXT, "bindings": {KEY: ACTION}})
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        bak = p.with_name(p.name + ".bak")
        bak.write_bytes(p.read_bytes())
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def main(argv) -> int:
    if len(argv) != 2 or argv[1] not in ("check", "merge"):
        print("usage: keybindings-merge.py check|merge", file=sys.stderr)
        return 2
    p = target()
    data, state = load(p)
    if argv[1] == "merge" and state == "missing":
        merge(p, data)
        state = "merged"
    print(state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
