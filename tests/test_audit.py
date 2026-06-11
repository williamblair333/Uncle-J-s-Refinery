# tests/test_audit.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "audit"))
import audit_lib
import collect_token_cost
import collect_maintenance

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

def test_write_json_strips_empties_but_preserves_missing(tmp_path):
    out = audit_lib.write_json(tmp_path / "sub/out.json",
                               {"a": 1, "b": [], "c": None, "missing": []})
    data = json.loads(out.read_text())
    assert data["a"] == 1
    assert "b" not in data and "c" not in data
    assert data["missing"] == []          # preserved: "ran clean" signal

def test_match_components_logic_inline_fixture():
    fixture = [{"id": "x", "commit_keywords": ["hnsw"],
                "file_patterns": ["scripts/mempalace-*"]}]
    assert audit_lib.match_components(fixture, subject="fix: hnsw repair") == {"x"}
    assert audit_lib.match_components(fixture, subject="zzz",
                                      files=["scripts/mempalace-repair-now.sh"]) == {"x"}
    assert audit_lib.match_components(fixture, subject="docs: typo",
                                      files=["README.md"]) == set()


def test_split_md_sections():
    md = "# Title\nintro\n## Alpha\naaaa\n## Beta\nbbbb\nbbbb\n"
    sections = collect_token_cost.split_sections(md)
    names = [s[0] for s in sections]
    assert names == ["(preamble)", "Alpha", "Beta"]
    assert sections[2][1].count("bbbb") == 2

def test_split_sections_ignores_fenced_headings():
    md = "## Real\ntext\n```bash\n## not a heading\n```\nmore\n"
    names = [s[0] for s in collect_token_cost.split_sections(md)]
    assert names == ["(preamble)", "Real"]

SAMPLE_LOG = """abc1|2026-06-10|fix: hnsw corruption repair in nightly cron
scripts/mempalace-repair-now.sh

def2|2026-06-09|feat: telegram inline button
features/telegram-gateway/bot.py

ghi3|2026-06-08|docs: session-end notes
HANDOFF.md
"""

def test_parse_git_log():
    commits = collect_maintenance.parse_log(SAMPLE_LOG)
    assert len(commits) == 3
    assert commits[0] == ("abc1", "2026-06-10",
                          "fix: hnsw corruption repair in nightly cron",
                          ["scripts/mempalace-repair-now.sh"])

def test_classify_maintenance():
    assert collect_maintenance.is_maintenance("fix: hnsw corruption repair") is True
    assert collect_maintenance.is_maintenance("feat: telegram inline button") is False
    assert collect_maintenance.is_maintenance("repair cron dedup") is True

def test_aggregate_by_component():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    agg = collect_maintenance.aggregate(comps, collect_maintenance.parse_log(SAMPLE_LOG))
    assert agg["mempalace"]["commits"] == 1
    assert agg["mempalace"]["maintenance_commits"] == 1
    assert agg["telegram"]["maintenance_commits"] == 0


# Integration test: intentionally coupled to the live manifest's routing-policy entry.
def test_map_sections_to_components():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    out = collect_token_cost.map_sections(comps,
        [("Retrieval Stack Routing Policy", "x" * 400), ("Unknown Heading", "y" * 400)])
    assert out["routing-policy"]["est_tokens"] == 100
    assert out["_unmapped"]["est_tokens"] == 100
