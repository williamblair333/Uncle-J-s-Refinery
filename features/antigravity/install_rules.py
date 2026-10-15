#!/usr/bin/env python3
"""Install the Refinery rules block into agy's global rules file (~/.gemini/GEMINI.md).

The file is user-owned, so only the text between the block's start and end markers is
ever replaced; everything else is kept. First install appends the block. A .bak of the
previous file is kept and the write is atomic. `{STACK_ROOT}` in the block is replaced
with this repo's path.

Usage: install_rules.py [--target PATH] [--block PATH] [--uninstall]
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STACK_ROOT = HERE.parent.parent
DEFAULT_TARGET = Path.home() / ".gemini" / "GEMINI.md"
START = "<!-- UNCLE-J-AGY-START -->"
END = "<!-- UNCLE-J-AGY-END -->"


def install(target: Path, block: str, start: str = START, end: str = END) -> None:
    target = Path(target)
    text = target.read_text(encoding="utf-8") if target.is_file() else ""
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if block:
        new = pattern.sub(lambda _: block.strip(), text) if pattern.search(text) else (
            text.rstrip("\n") + ("\n\n" if text.strip() else "") + block.strip() + "\n")
    else:
        new = pattern.sub("", text).rstrip("\n") + "\n"
    if new == text:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, target)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("--block", type=Path, default=HERE / "rules-block.md")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args(argv)
    block = "" if args.uninstall else args.block.read_text(encoding="utf-8").replace(
        "{STACK_ROOT}", str(STACK_ROOT))
    install(args.target, block)
    print(f"{'removed from' if args.uninstall else 'installed in'} {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
