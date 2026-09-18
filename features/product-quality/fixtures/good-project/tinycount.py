#!/usr/bin/env python3
"""Count the words in a file. Gate fixture: this one is expected to pass."""
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: tinycount.py FILE", file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    if not source.exists():
        print(f"no such file: {source}", file=sys.stderr)
        return 1
    words = len(source.read_text().split())
    Path("/tmp/tinycount.out").write_text(f"{words}\n")
    print(f"counted {words} words")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
