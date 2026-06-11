# scripts/audit/audit_lib.py
"""Shared helpers for the pay-for-itself audit collectors. Stdlib only."""
import fnmatch
import json
from pathlib import Path


def load_components(manifest_path):
    data = json.loads(Path(manifest_path).read_text())
    return data["components"]


def est_tokens(blob: bytes) -> int:
    # Documented estimate: ~4 bytes/token for English/markdown.
    return len(blob) // 4


def match_components(components, subject="", files=()):
    """Return the set of component ids matching a commit subject and file list."""
    subject_l = subject.lower()
    hits = set()
    for c in components:
        if any(k in subject_l for k in c.get("commit_keywords", [])):
            hits.add(c["id"])
            continue
        for f in files:
            if any(fnmatch.fnmatch(f, pat) for pat in c.get("file_patterns", [])):
                hits.add(c["id"])
                break
    return hits


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Strip empty collections explicitly (CLAUDE.md MCP response rule).
    clean = {k: v for k, v in payload.items() if v is not None and v != [] and v != {}}
    path.write_text(json.dumps(clean, indent=1, ensure_ascii=False))
    return path
