#!/usr/bin/env python3
"""Refuse a pre-mortem whose risky CLEARs cite no evidence.

Called by write-clearance-token.sh before it writes a token:
    python3 -I check_clears.py <analysis-file>
Exit 0 = the analysis may earn a token; 1 = refused (reasons on stderr); 2 = usage.

Why (2026-11-27): a rhcsa-lab pre-mortem cleared RECOVERY with "vm-destroy is the
rollback; the ISO is never modified". Nobody checked what vm-destroy deleted; it
deleted the ISO. SKILL.md already said an unverified runtime claim is not a CLEAR,
but nothing enforced it. This does, for the dimensions where a wrong CLEAR loses
data, and for any CLEAR that makes an absolute claim.

Rules, per dimension block (from its `[ NAME ]` header to the next header or the
SEVERITY/SUMMARY/STATUS line):
  1. The file must hold at least one dimension block and a STATUS or SUMMARY line.
  2. A ✓ CLEAR on RECOVERY, DATA INTEGRITY or SECURITY must cite what was checked:
     `(checked: <command and its output | file:line | doc line>)`, 8+ characters.
  3. Any other ✓ CLEAR that claims never / always / cannot / can't / impossible /
     guaranteed / only ever / nothing else must cite the same way.
The citation is the model's own words, so it can still lie. What it can't do any
more is clear a dimension without saying what it looked at, which is how the ISO
went: the claim was plausible and nobody looked.
"""
from __future__ import annotations

import re
import sys

HEADER = re.compile(r"^\s*\[\s*([A-Z][A-Z /&-]*?)\s*\]\s*(.*)$")
# A block ends at the summary, or at any other top-level label (TOKEN SCOPE …), so a
# citation written there can't count for the dimension above it.
END = re.compile(r"^\s*[│┌└╔║]?\s*(SEVERITY SUMMARY|SUMMARY|STATUS|TOKEN SCOPE|SURFACES[A-Z ]*|"
                 r"CLASSIFICATION|DIMENSIONS CHECKED)\b", re.I)
CLEAR = re.compile(r"✓\s*CLEAR|\bCLEAR\b\s*[:—–-]", re.I)
CITE = re.compile(r"\(?\bchecked\s*:\s*([^)\n]{8,})", re.I)
RISKY = {"RECOVERY", "DATA INTEGRITY", "SECURITY"}
ABSOLUTE = re.compile(
    r"\b(never|always|cannot|can't|can not|impossible|guaranteed|only ever|nothing else)\b", re.I)


def blocks(text: str) -> tuple[list[tuple[str, str]], bool]:
    out: list[tuple[str, str]] = []
    name, body, ended = None, [], False
    for line in text.splitlines():
        m = HEADER.match(line)
        if m and m.group(1).strip().upper() == "TOKEN SCOPE":
            if name:
                out.append((name, "\n".join(body)))
            name, body = None, []
            continue
        if m:
            if name:
                out.append((name, "\n".join(body)))
            name, body = m.group(1).strip().upper(), [m.group(2)]
            continue
        if END.match(line):
            ended = True
            if name:
                out.append((name, "\n".join(body)))
            name, body = None, []
            continue
        if name:
            body.append(line)
    if name:
        out.append((name, "\n".join(body)))
    return out, ended


def problems(text: str) -> list[str]:
    found, ended = blocks(text)
    if not found:
        return ["no dimension blocks ([ NAME ] ✓ CLEAR / ⚠ …) found: pass the analysis itself"]
    errs = [] if ended else ["no STATUS or SUMMARY line: pass the whole analysis"]
    for name, body in found:
        # the verdict is the first line that carries one: ✓ CLEAR, ⚠/⛔, or a severity word
        first = next((ln for ln in body.split("\n")
                      if CLEAR.search(ln) or re.match(r"\s*(⚠|⛔|(LOW|MEDIUM|HIGH|CATASTROPHIC)\b)", ln)), "")
        if not CLEAR.search(first) or re.match(r"\s*(⚠|⛔|(LOW|MEDIUM|HIGH|CATASTROPHIC)\b)", first):
            continue
        if CITE.search(body):
            continue
        claim = re.sub(r"^\s*✓?\s*CLEAR\s*[:—–-]?\s*", "", first).strip()[:120]
        if name in RISKY:
            errs.append(f"[ {name} ] CLEAR cites nothing checked: \"{claim}\". "
                        "Add (checked: <command + output | file:line | doc line>) or make it a finding.")
        elif ABSOLUTE.search(body):
            word = ABSOLUTE.search(body).group(0)
            errs.append(f"[ {name} ] CLEAR claims \"{word}\" without a citation: \"{claim}\". "
                        "Add (checked: …) or make it a finding.")
    return errs


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_clears.py <analysis-file>", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        print(f"refusing: can't read the analysis file: {e}", file=sys.stderr)
        return 1
    errs = problems(text)
    for e in errs:
        print(f"refusing: {e}", file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
