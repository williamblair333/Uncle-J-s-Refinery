"""scripts/guide_bench — the deterministic parts (no model calls)."""

import json
from pathlib import Path

from scripts.guide_bench.bench import QUERIES, compact_guide, registry, route

GUIDE = """## jcodemunch-mcp (v1)

Use it.

### Quick start
1. `list_repos` — check.
2. `search_symbols` — find.

### All tools
**Indexing:** `index_folder`, `index_repo`
**Search:** `search_symbols`, `search_text`

The built-in tools stay the right choice for a file you are about to edit.
"""


def test_compact_drops_only_the_catalogue():
    c = compact_guide(GUIDE)
    assert "### All tools" not in c and "index_repo" not in c
    assert "### Quick start" in c and "`list_repos`" in c
    assert c.rstrip().endswith("about to edit.")


def test_registry_is_every_backticked_name_once():
    assert registry(GUIDE) == ["list_repos", "search_symbols", "index_folder",
                               "index_repo", "search_text"]


def test_queries_fixture_has_20_with_answers():
    qs = json.loads(Path(QUERIES).read_text())
    assert len(qs) == 20
    assert all(q["q"] and q["ok"] for q in qs)


class FakeRail:
    def __init__(self, text):
        self.text = text

    def chat(self, *a, **kw):
        return {"text": self.text}


def test_route_picks_first_registry_name_in_reply():
    names = ["search_text", "search_symbols"]
    assert route(FakeRail("Use `search_symbols`."), names, "g", "q") == "search_symbols"
    assert route(FakeRail("no idea"), names, "g", "q") == "no idea"
