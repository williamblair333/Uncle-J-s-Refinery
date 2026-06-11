# tests/test_audit.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "audit"))
import audit_lib

REPO = Path(__file__).parent.parent

def test_manifest_loads_and_has_required_fields():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    assert len(comps) >= 8
    for c in comps:
        assert c["id"], "every component needs an id"
        assert isinstance(c.get("commit_keywords", []), list)
        assert isinstance(c.get("file_patterns", []), list)

def test_est_tokens():
    assert audit_lib.est_tokens(b"") == 0
    assert audit_lib.est_tokens(b"abcd" * 100) == 100  # 400 bytes -> 100 tokens

def test_match_component_by_keyword_and_file():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    hit = audit_lib.match_components(comps, subject="fix: hnsw corruption repair",
                                     files=["scripts/mempalace-repair-now.sh"])
    assert "mempalace" in hit
    miss = audit_lib.match_components(comps, subject="docs: typo", files=["README.md"])
    assert miss == set()
