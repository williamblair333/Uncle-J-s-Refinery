"""scripts/web2md.py: output paths stay inside --out, slugs are safe, front matter is right.

The helpers import nothing beyond the stdlib (trafilatura is imported lazily), so these
run in the stack venv. Fetching is exercised live by hand, not here: it needs network.
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "web2md", Path(__file__).resolve().parent.parent / "scripts" / "web2md.py")
web2md = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(web2md)


def test_slug_is_safe_and_never_empty():
    assert web2md.slug("Docs/Getting Started?x=1") == "docs-getting-started-x-1"
    assert web2md.slug("../../.bashrc") == "bashrc"
    assert web2md.slug("") == "index"
    assert web2md.slug("...") == "index"


def test_out_path_is_host_then_path_slug(tmp_path):
    p = web2md.out_path(tmp_path, "https://docs.astral.sh/uv/guides/scripts/")
    assert p == (tmp_path / "docs.astral.sh" / "uv-guides-scripts.md").resolve()
    assert web2md.out_path(tmp_path, "https://example.org/").name == "index.md"
    assert web2md.out_path(tmp_path, "https://example.org/a?page=2").name == "a-page-2.md"


@pytest.mark.parametrize("url", [
    "https://evil.example/../../../../etc/passwd",
    "https://evil.example/%2e%2e/%2e%2e/home",
    "https://..%2f..%2f/x",
])
def test_traversal_attempts_stay_inside_out(tmp_path, url):
    try:
        p = web2md.out_path(tmp_path, url)
    except ValueError:
        return
    assert p.is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "javascript:alert(1)", "/relative"])
def test_non_http_urls_refused(tmp_path, url):
    with pytest.raises(ValueError):
        web2md.out_path(tmp_path, url)


def test_heading_links_become_headings():
    md = ("[Running scripts](https://docs.astral.sh#running-scripts)\n\nintro\n\n"
          "[Using a shebang](https://docs.astral.sh#using-a-shebang)\n\n"
          "see [the guide](https://docs.astral.sh#x) inline\n")
    out = web2md.fix_headings(md, "Running scripts")
    assert out.splitlines()[0] == "# Running scripts"
    assert "## Using a shebang" in out.splitlines()
    assert "see [the guide](https://docs.astral.sh#x) inline" in out     # an inline link stays


def test_sphinx_pilcrow_permalinks_are_stripped():
    assert web2md.fix_headings("## Basic use[¶](https://docs.python.org#basic-use)\n", None) == "## Basic use\n"


def test_render_front_matter():
    text = web2md.render("https://e.org/a", "\n# Hi\n\nbody\n", 'A "quoted" title', "2026-10-22")
    assert text.splitlines()[:5] == ["---", "source: https://e.org/a", "fetched: 2026-10-22",
                                     'title: "A \\"quoted\\" title"', "---"]
    assert text.endswith("# Hi\n\nbody\n")
