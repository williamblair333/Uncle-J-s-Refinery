#!/usr/bin/env python
"""Mirror the Obsidian vault's markdown into the memweave corpus.

memweave's corpus is everything under ``<workspace>/memory/**.md`` (verified:
``MemWeave.index`` recurses, and files outside ``memory/`` are not indexed). Until
now the only writer was ``export_transcripts.py``, so the corpus held session
transcripts and nothing else — which meant the prior-art rule ("have we solved
this before?") searched past the vault, the one store that holds the *decisions*
rather than the conversations that produced them.

This copies the vault's notes into ``<workspace>/memory/vault/<relpath>.md`` so
they become searchable alongside the transcripts.

**The mirror is derived. Never edit it — edit the vault.** Anything written into
the destination is overwritten or pruned on the next run.

Two properties matter more than the copying and are the reason this is a script
rather than an rsync line:

  * **Exclusions fail closed.** The vault holds a personal-context note (health,
    key people, beliefs — which the vault's own rules mark as never boot-loaded)
    and an archive carrying a plaintext credential. Those folders are excluded,
    and any top-level folder this script does not recognise is *also* excluded,
    loudly, rather than silently mirrored into a cross-project searchable index.
    A denylist alone fails open; the census below is what makes it fail closed.

  * **Pruning cannot escape its own directory.** Deletions in the vault must
    propagate, so orphans in the destination are removed — and a destination
    computed one level too high would delete the whole transcript corpus.
    ``_resolve_dest`` asserts the target is a strict subpath of ``memory/`` named
    exactly ``vault`` before any unlink, and only ``*.md`` files are removed.

Usage:
  .venv-memweave/bin/python scripts/memweave/mirror_vault.py
  .venv-memweave/bin/python scripts/memweave/mirror_vault.py --vault DIR --out WORKSPACE
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Same env var the vault Stop hook (scripts/vault-session-check.sh) already uses,
# so there is one knob for "where is the vault", not two.
DEFAULT_VAULT = Path(os.environ.get("VAULT_ROOT") or "/opt/proj/jaredrhod/vaults/brain")
# Must NOT live under a dir literally named ".memweave" — see export_transcripts.py.
DEFAULT_WORKSPACE = Path(os.path.expanduser("~/.uncle-j-memory"))

# The mirror's own subdirectory under <workspace>/memory. Load-bearing: the prune
# guard asserts the destination's final component is exactly this.
MIRROR_DIRNAME = "vault"

# Obsidian folders carry a sort prefix ("11 - Personal"). Matching on the
# normalized name means renumbering a folder cannot silently disable its
# exclusion — which a literal-string denylist would.
_PREFIX_RE = re.compile(r"^\d+\s*-\s*")

# Top-level vault entries this script knows about. Anything absent is excluded
# and reported (see classify_top_level) — a new folder must be classified here
# deliberately, never mirrored by default.
EXCLUDED_TOP_LEVEL = {
    # Holds Personal Context.md: health, key people, beliefs. The vault's own
    # rules keep it out of every boot-loaded file for exactly this reason; a
    # cross-project semantic index has a wider blast radius still.
    "personal",
    # Frozen migrated-memory snapshot containing a plaintext credential
    # (VAULT-INDEX.md's version-control rule). Confirmed by scan: 1
    # credential-shaped line here, 0 across everything mirrored.
    "archive",
}

INCLUDED_TOP_LEVEL = {
    "inbox",
    "daily notes",
    "uncle j's refinery",
    "fog of chess",
    "campaign forge",
    "gitea",
    "mafski",
    "partikus",
    "immich",
    "wine",
    "magicians almanac",
    "resources",
}


def normalize_folder(name: str) -> str:
    """'11 - Personal' -> 'personal'. Sort-prefix and case are not identity."""
    return _PREFIX_RE.sub("", name).strip().casefold()


def classify_top_level(name: str) -> str:
    """Classify a top-level vault entry: 'include' | 'exclude' | 'unknown'.

    'unknown' is treated as 'exclude' by the caller, and reported. The vault
    gains folders routinely (twelve in its first four days), and nothing about
    creating one prompts anybody to revisit this file — so the default for an
    unrecognised folder has to be "keep it out, and say so", not "ship it".
    """
    norm = normalize_folder(name)
    if norm in EXCLUDED_TOP_LEVEL:
        return "exclude"
    if norm in INCLUDED_TOP_LEVEL:
        return "include"
    return "unknown"


def is_hidden(rel: Path) -> bool:
    """True when any path component is a dotfile/dotdir (.git, .obsidian, .trash)."""
    return any(part.startswith(".") for part in rel.parts)


def iter_source_files(vault: Path) -> tuple[list[Path], list[str]]:
    """Vault markdown to mirror, as paths relative to the vault root.

    Returns (relative paths, sorted names of unknown top-level entries). Root-level
    notes (VAULT-INDEX.md, Active Priorities.md) have no folder to classify and are
    always included — they are the map and the open-work queue, the two files a
    prior-art search most wants.
    """
    keep: list[Path] = []
    unknown: set[str] = set()
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        if is_hidden(rel):
            continue
        if len(rel.parts) == 1:
            keep.append(rel)
            continue
        verdict = classify_top_level(rel.parts[0])
        if verdict == "include":
            keep.append(rel)
        elif verdict == "unknown":
            unknown.add(rel.parts[0])
    return keep, sorted(unknown)


def _resolve_dest(workspace: Path) -> Path:
    """Resolve the mirror directory, refusing any target that could prune the corpus.

    The prune step deletes files. If this ever resolved to <workspace>/memory the
    delete loop would take out every transcript document — recoverable by
    re-export, but the dream-synthesis notes and the pre-mortem audit sink that
    also live there are not regenerable from transcripts. Three assertions, all
    cheap, all before any unlink.
    """
    memory_root = (workspace / "memory").resolve()
    dest = (memory_root / MIRROR_DIRNAME).resolve()
    if dest.name != MIRROR_DIRNAME:
        raise ValueError(f"refusing to mirror: dest name is {dest.name!r}, not {MIRROR_DIRNAME!r}")
    if dest == memory_root:
        raise ValueError(f"refusing to mirror: dest resolves to the corpus root {memory_root}")
    if memory_root not in dest.parents:
        raise ValueError(f"refusing to mirror: {dest} is not under {memory_root}")
    return dest


def mirror(vault: Path, workspace: Path) -> dict:
    """Copy vault markdown into <workspace>/memory/vault, pruning orphans.

    Copies are byte-identical to the source so memweave's SHA-256 compare skips
    unchanged files, and so the mirror can be audited with a plain `diff -r`.
    Returns a counts dict; the caller decides the exit code.
    """
    dest = _resolve_dest(workspace)
    wanted, unknown = iter_source_files(vault)

    copied = unchanged = failed = 0
    written: set[Path] = set()

    for rel in wanted:
        src = vault / rel
        out = dest / rel
        try:
            data = src.read_bytes()
            if out.exists() and out.read_bytes() == data:
                unchanged += 1
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
                copied += 1
            written.add(out.resolve())
        except Exception as exc:
            # Contain the blast radius to one note, but stay loud: a bare
            # `continue` would trade a crash for a silently partial corpus, and
            # nothing downstream would notice — the healthcheck measures index
            # freshness, not completeness. Forced non-zero exit in main().
            print(f"mirror_vault: FAILED {rel}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1

    # Prune orphans so a note deleted in the vault leaves the index too. Scoped to
    # *.md under the guarded dest — never a recursive tree delete.
    pruned = 0
    if dest.exists():
        for stale in sorted(dest.rglob("*.md")):
            if stale.resolve() not in written:
                stale.unlink()
                pruned += 1
        # Tidy directories the prune emptied, deepest first. Never removes dest.
        for d in sorted((p for p in dest.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()

    return {"copied": copied, "unchanged": unchanged, "pruned": pruned,
            "failed": failed, "unknown_folders": unknown, "dest": dest}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=str(DEFAULT_VAULT),
                    help="vault root (default: $VAULT_ROOT or the jaredrhod brain vault)")
    ap.add_argument("--out", default=str(DEFAULT_WORKSPACE),
                    help="memweave workspace dir (mirror lands in <out>/memory/vault)")
    args = ap.parse_args()

    vault = Path(os.path.expanduser(args.vault))
    workspace = Path(os.path.expanduser(args.out))

    # No vault on this machine (Windows, a fresh clone, another host) is the
    # normal case, not an error. Exit clean — the caller must still index the
    # transcripts it just exported.
    if not vault.is_dir():
        print(f"mirror_vault: skipped — no vault at {vault}")
        return 0

    try:
        r = mirror(vault, workspace)
    except ValueError as exc:
        print(f"mirror_vault: {exc}", file=sys.stderr)
        return 1

    print(f"mirror_vault: {vault} -> {r['dest']}")
    print(f"  copied {r['copied']}, unchanged {r['unchanged']}, pruned {r['pruned']}, "
          f"failed {r['failed']}")
    if r["unknown_folders"]:
        # Loud on purpose. This is the fail-closed half of the exclusion policy:
        # the folder was kept OUT, and somebody has to decide where it belongs.
        print("mirror_vault: EXCLUDED unrecognised top-level folder(s): "
              + ", ".join(r["unknown_folders"]), file=sys.stderr)
        print("  classify each in INCLUDED_TOP_LEVEL or EXCLUDED_TOP_LEVEL "
              "(scripts/memweave/mirror_vault.py) before they can be searched",
              file=sys.stderr)
        return 1
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
