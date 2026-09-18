#!/usr/bin/env python3
"""Gate fixture: the false-green failure mode.

Depends on a package the README never mentions, catches the resulting error,
prints something reassuring, and exits 0 — so any check that trusts exit codes
reports success on a tool that did nothing. Expected result: FAIL.
"""
import sys
from pathlib import Path


def main() -> int:
    try:
        import requests  # undocumented dependency, absent in a clean container
    except ImportError:
        print("note: running in reduced mode")
        return 0
    Path("/tmp/brittle.out").write_text(f"summary via {requests.__name__}\n")
    print("summary written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
