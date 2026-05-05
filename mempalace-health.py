#!/opt/proj/Uncle-J-s-Refinery/.venv/bin/python
"""
MemPalace health check — run before or after MCP server starts.
Exits 0 if healthy, 1 if degraded (warnings), 2 if critical.
"""
import os
import pickle
import sqlite3
import struct
import sys
from pathlib import Path

PALACE = Path(os.environ.get("MEMPALACE_PATH", Path.home() / ".mempalace" / "palace"))
WAL_WARN_THRESHOLD = 10_000   # entries in embeddings_queue before warning
WAL_CRIT_THRESHOLD = 100_000  # critical
SIZE_SKEW_FACTOR   = 3.0      # data_level0.bin larger than expected by this factor


def check_sqlite(palace: Path) -> list[str]:
    db = palace / "chroma.sqlite3"
    if not db.exists():
        return [f"CRIT: chroma.sqlite3 missing at {db}"]
    issues = []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            # BLOB seq_ids — re-check even after migration
            for table in ("embeddings", "max_seq_id"):
                try:
                    blob_count = conn.execute(
                        f"SELECT count(*) FROM {table} WHERE typeof(seq_id)='blob'"
                    ).fetchone()[0]
                    if blob_count:
                        issues.append(f"CRIT: {blob_count} BLOB seq_ids in {table} — run _fix_blob_seq_ids()")
                except sqlite3.OperationalError:
                    pass

            # WAL queue depth
            wal_rows = conn.execute(
                "SELECT topic, count(*) FROM embeddings_queue GROUP BY topic"
            ).fetchall()
            total_wal = sum(r[1] for r in wal_rows)
            if total_wal > WAL_CRIT_THRESHOLD:
                issues.append(f"CRIT: embeddings_queue has {total_wal:,} uncompacted entries — compactor may be stuck")
            elif total_wal > WAL_WARN_THRESHOLD:
                issues.append(f"WARN: embeddings_queue has {total_wal:,} entries — compactor lag")

            # Collection / segment inventory
            segs = conn.execute(
                "SELECT s.id, s.scope, c.name FROM segments s JOIN collections c ON s.collection=c.id"
            ).fetchall()
            collections = {row[2] for row in segs}
            for col in collections:
                vector_segs = [r for r in segs if r[2] == col and r[1] == "VECTOR"]
                meta_segs   = [r for r in segs if r[2] == col and r[1] == "METADATA"]
                if not vector_segs:
                    issues.append(f"WARN: collection '{col}' has no VECTOR segment")
                if not meta_segs:
                    issues.append(f"WARN: collection '{col}' has no METADATA segment")
    except Exception as e:
        issues.append(f"CRIT: cannot open chroma.sqlite3: {e}")
    return issues


def check_hnsw_segment(seg_dir: Path, col_name: str) -> list[str]:
    issues = []
    required = ["data_level0.bin", "header.bin", "length.bin", "link_lists.bin", "index_metadata.pickle"]
    missing = [f for f in required if not (seg_dir / f).exists()]
    if missing:
        # Absent binary files = fresh empty index (valid after deletion-fix); not an error.
        return []

    # Parse header.bin
    try:
        hdr = (seg_dir / "header.bin").read_bytes()
        if len(hdr) < 24:
            issues.append(f"WARN [{col_name}]: header.bin too small ({len(hdr)} bytes)")
            return issues
        max_elements  = struct.unpack_from("<I", hdr, 12)[0]
        cur_elements  = struct.unpack_from("<I", hdr, 20)[0]
    except Exception as e:
        issues.append(f"WARN [{col_name}]: cannot parse header.bin: {e}")
        return issues

    # Parse index_metadata.pickle
    try:
        pkl_path = seg_dir / "index_metadata.pickle"
        with open(pkl_path, "rb") as f:
            meta = pickle.load(f)
        dim = meta.get("dimensionality")
        n_labels = len(meta.get("id_to_label", {}))
        total_added = meta.get("total_elements_added", 0)
    except Exception as e:
        issues.append(f"WARN [{col_name}]: cannot parse index_metadata.pickle: {e}")
        return issues

    # data_level0.bin size sanity check
    dl0_size = (seg_dir / "data_level0.bin").stat().st_size
    if dim and cur_elements > 0:
        # Rust hnswlib-rs: each row = M*4 (neighbors) + dim*4 (vector) + overhead (~12 bytes)
        # Conservative estimate: at least dim*4 bytes per element
        min_expected = cur_elements * dim * 4
        max_expected = cur_elements * (dim * 4 + 200) * SIZE_SKEW_FACTOR
        if dl0_size > max_expected:
            issues.append(
                f"CRIT [{col_name}]: data_level0.bin is {dl0_size/1e9:.2f}GB "
                f"but only {cur_elements} elements — possible old Python hnswlib format. "
                f"Backup and delete the segment directory to force rebuild."
            )

    # dimensionality=None is normal in chromadb 1.5.x (Rust doesn't use the pickle dim).
    # Only flag if BOTH dim is None AND the binary looks unexpectedly large (old Python hnswlib).
    if dim is None and dl0_size > 100_000_000:  # >100MB with no known dim = suspicious
        issues.append(
            f"WARN [{col_name}]: index_metadata.pickle has dimensionality=None "
            f"and data_level0.bin is {dl0_size/1e6:.0f}MB — possible stale Python hnswlib format"
        )

    if max_elements > 0 and cur_elements > max_elements:
        issues.append(f"WARN [{col_name}]: cur_element_count ({cur_elements}) > max_elements ({max_elements})")

    # Orphaned labels: pickle says N elements but header says fewer
    if n_labels > cur_elements and cur_elements > 0:
        gap = n_labels - cur_elements
        if gap > 1000:
            issues.append(f"WARN [{col_name}]: pickle has {n_labels} labels but header has {cur_elements} elements ({gap} orphans — high fragmentation)")

    return issues


def check_all_hnsw(palace: Path) -> list[str]:
    db = palace / "chroma.sqlite3"
    if not db.exists():
        return []
    issues = []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT s.id, c.name FROM segments s JOIN collections c ON s.collection=c.id WHERE s.scope='VECTOR'"
            ).fetchall()
        for seg_id, col_name in rows:
            seg_dir = palace / seg_id
            if seg_dir.is_dir():
                issues.extend(check_hnsw_segment(seg_dir, col_name))
    except Exception as e:
        issues.append(f"WARN: could not enumerate HNSW segments: {e}")
    return issues


def main():
    if not PALACE.exists():
        print(f"CRIT: palace directory missing: {PALACE}", file=sys.stderr)
        sys.exit(2)

    all_issues = []
    all_issues.extend(check_sqlite(PALACE))
    all_issues.extend(check_all_hnsw(PALACE))

    # Live open test — catches Rust hnswlib-rs loader errors that static checks miss
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(PALACE))
        cols = client.list_collections()
        for col in cols:
            try:
                c = client.get_collection(col.name)
                c.query(query_texts=["health check"], n_results=1)
            except Exception as e:
                all_issues.append(f"CRIT [{col.name}]: live query failed: {e}")
    except Exception as e:
        all_issues.append(f"CRIT: cannot open PersistentClient: {e}")

    if not all_issues:
        print(f"OK: MemPalace healthy at {PALACE}")
        sys.exit(0)

    for issue in all_issues:
        print(issue)

    crits = [i for i in all_issues if i.startswith("CRIT")]
    sys.exit(2 if crits else 1)


if __name__ == "__main__":
    main()
