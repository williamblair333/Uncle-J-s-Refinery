#!/usr/bin/env python3
"""Delete all drawers for a given wing from the MemPalace.
Usage: python mempalace-delete-wing.py <wing-name> [--dry-run]
"""
import sys, os, argparse
os.environ.setdefault("CHROMA_API_IMPL", "chromadb.api.segment.SegmentAPI")

import chromadb

PALACE = os.path.expanduser("~/.mempalace/palace")
COLLECTION = "mempalace_drawers"
BATCH = 500

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wing", help="Wing name to delete")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=PALACE)
    col = client.get_collection(COLLECTION)

    total_before = col.count()
    print(f"Total drawers before: {total_before:,}")

    # Count matching first
    result = col.get(where={"wing": args.wing}, include=[], limit=1)
    # ChromaDB doesn't give a direct count by filter — get all IDs in batches
    offset = 0
    all_ids = []
    while True:
        batch = col.get(where={"wing": args.wing}, include=[], limit=BATCH, offset=offset)
        ids = batch["ids"]
        if not ids:
            break
        all_ids.extend(ids)
        offset += len(ids)
        print(f"  Found {len(all_ids):,} so far...", end="\r")

    print(f"\nDrawers in wing '{args.wing}': {len(all_ids):,}")

    if not all_ids:
        print("Nothing to delete.")
        return

    if args.dry_run:
        print("DRY RUN — no changes made.")
        return

    confirm = input(f"Delete {len(all_ids):,} drawers from wing '{args.wing}'? [y/N] ")
    if confirm.lower() != "y":
        print("Aborted.")
        return

    deleted = 0
    for i in range(0, len(all_ids), BATCH):
        chunk = all_ids[i:i+BATCH]
        col.delete(ids=chunk)
        deleted += len(chunk)
        print(f"  Deleted {deleted:,}/{len(all_ids):,}...", end="\r")

    print(f"\nDeleted {deleted:,} drawers.")
    total_after = col.count()
    print(f"Total drawers after: {total_after:,}  (removed {total_before - total_after:,})")
    print("\nRun `mempalace repair --mode from-sqlite --yes --archive-existing` to rebuild HNSW without the deleted wing.")

if __name__ == "__main__":
    main()
