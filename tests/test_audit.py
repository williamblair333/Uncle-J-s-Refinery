# tests/test_audit.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "audit"))
import audit_lib
import collect_token_cost
import collect_maintenance
import collect_benefits
import build_scorecard

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
    assert collect_maintenance.is_maintenance("feat: add nightly repair cron") is False
    assert collect_maintenance.is_maintenance("docs: session-end — FTS5 repair notes") is False
    assert collect_maintenance.is_maintenance("Merge pull request #19 from fix/mempalace-repair") is False

def test_aggregate_by_component():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    agg = collect_maintenance.aggregate(comps, collect_maintenance.parse_log(SAMPLE_LOG))
    assert agg["mempalace"]["commits"] == 1
    assert agg["mempalace"]["maintenance_commits"] == 1
    assert agg["telegram"]["maintenance_commits"] == 0
    assert agg["mempalace"]["maintenance_share"] == 1.0
    assert agg["reliability"]["commits"] == 2   # "fix: hnsw ... cron" (cron keyword) + "docs: session-end notes" (session-end keyword)


# Integration test: intentionally coupled to the live manifest's routing-policy entry.
def test_map_sections_to_components():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    out = collect_token_cost.map_sections(comps,
        [("Retrieval Stack Routing Policy", "x" * 400), ("Unknown Heading", "y" * 400)])
    assert out["routing-policy"]["est_tokens"] == 100
    assert out["_unmapped"]["est_tokens"] == 100


SAMPLE_BLOCKS = """2026-06-10T10:00:00 grep-guard BLOCKED grep -r foo
2026-06-10T11:00:00 edit-surface-guard BLOCKED settings.json
2026-06-11T05:00:00 grep-guard BLOCKED grep -rn bar
2026-06-11T06:00:00 grep-guard ALLOWED grep foo
2026-06-11T07:00:00 BLOCKED something with no guardname token
"""

def test_count_hook_blocks():
    counts = collect_benefits.count_blocks(SAMPLE_BLOCKS)
    assert counts["grep-guard"] == 2          # ALLOWED line not counted
    assert counts["edit-surface-guard"] == 1
    assert counts["_unparsed"] == 1           # BLOCKED but no recognisable guard name

def test_mempalace_counts_missing_db(tmp_path):
    assert collect_benefits.mempalace_counts(tmp_path / "nope.sqlite3") is None

def test_scorecard_handles_non_numeric_nested_dict():
    bene = {"components": {"mempalace": {"weird": {"a": "x"}}}, "missing": []}
    md = build_scorecard.render({"components": {}}, {"components": {}}, bene)
    assert "weird=" in md   # rendered, not crashed


def test_scorecard_renders_all_components_and_flags_gaps():
    token = {"components": {"mempalace": {"est_tokens": 100, "sources": ["x"]}}}
    maint = {"components": {"mempalace": {"commits": 10, "maintenance_commits": 9,
                                          "maintenance_share": 0.9}}}
    bene = {"components": {}, "missing": ["benefits source"]}
    md = build_scorecard.render(token, maint, bene)
    assert "| mempalace |" in md
    assert "0.9" in md
    assert "benefits source" in md          # missing data surfaced, not hidden
    assert "Verdict" in md                  # column exists, left blank for judgment pass


def test_count_corrections_parses_jsonl_and_buckets_by_component():
    import collect_benefits
    sample = (
        '{"ts":"2026-06-11T10:00:00Z","component":"mempalace","summary":"wrong path"}\n'
        '{"ts":"2026-06-11T11:00:00Z","component":"mempalace","summary":"stale fact"}\n'
        '{"ts":"2026-06-11T12:00:00Z","component":"telegram","summary":"bad offset claim"}\n'
        'not json — tolerated\n'
    )
    counts = collect_benefits.count_corrections(sample)
    assert counts["mempalace"] == 2
    assert counts["telegram"] == 1
    assert counts["_unparsed"] == 1


def test_last_run_age_days_from_iso():
    import collect_benefits, datetime
    now = datetime.datetime(2026, 6, 11, tzinfo=datetime.timezone.utc)
    age = collect_benefits.iso_age_days("2026-06-09T13:03:17Z", now=now)
    assert age == 2.0
    assert collect_benefits.iso_age_days("garbage", now=now) is None


def test_count_log_lines_matching():
    import collect_benefits
    log = ("[2026-06-11 08:20:01] Polling Telegram (offset=1)\n"
           "[2026-06-11 08:20:01] getUpdates returned ok=false\n"
           "[2026-06-11 08:21:01] Polling Telegram (offset=2)\n")
    assert collect_benefits.count_matching(log, "Polling Telegram") == 2


def test_count_dreaming_runs_vs_skips():
    import collect_benefits
    log = ("2026-06-10T13:03:17Z skip: no traces since ...\n"
           "2026-06-09T02:00:00Z dreamed: wrote 3 playbooks\n"
           "2026-06-08T02:00:00Z skip: no traces\n")
    stats = collect_benefits.dreaming_run_stats(log)
    assert stats["skips"] == 2
    assert stats["runs"] == 1
