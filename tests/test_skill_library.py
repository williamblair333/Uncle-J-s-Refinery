"""Tests for scripts/skill_library.py — skills kept on disk, pulled into global-skills/ one
at a time, never loaded wholesale."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import skill_library as sl  # noqa: E402


def _lib(tmp_path):
    lib = tmp_path / "skill-library" / "sci"
    for name, desc in (("astropy", "Astronomy with Astropy."),
                       ("rdkit", "Chemistry toolkit.\nSecond line.")):
        d = lib / "skills" / name
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc.splitlines()[0]}\n"
                                    "license: MIT\n---\n# body\n")
        (d / "references" / "a.md").write_text("ref")
    (lib / "LICENSE.md").write_text("MIT License\n\nCopyright (c) 2025 K-Dense Inc.\n")
    return lib


def _scan_ok(path):
    return "SAFE", ""


def test_list_skills_reads_name_and_description(tmp_path):
    lib = _lib(tmp_path)
    got = sl.list_skills(lib.parent)
    assert ("sci", "astropy", "Astronomy with Astropy.") in got
    assert len(got) == 2


def test_list_skills_filter(tmp_path):
    lib = _lib(tmp_path)
    assert [r[1] for r in sl.list_skills(lib.parent, "chem")] == ["rdkit"]


def test_add_copies_skill_with_license_and_upstream(tmp_path):
    lib = _lib(tmp_path)
    dest = tmp_path / "global-skills"
    out = sl.add_skill(lib.parent, "astropy", dest, scan=_scan_ok,
                       commit=lambda p: ("abc1234", "2026-10-12"),
                       remote=lambda p: "https://github.com/K-Dense-AI/scientific-agent-skills")
    assert out == dest / "astropy"
    assert (out / "SKILL.md").read_text().startswith("---\nname: astropy")
    assert (out / "references" / "a.md").exists()
    assert "K-Dense Inc." in (out / "LICENSE").read_text()
    up = (out / "UPSTREAM").read_text()
    assert "Vendored from https://github.com/K-Dense-AI/scientific-agent-skills" in up
    assert "Path: skills/astropy" in up and "Commit: abc1234 (2026-10-12)" in up
    assert "Scan: SAFE" in up


def test_add_refuses_to_overwrite(tmp_path):
    lib = _lib(tmp_path)
    dest = tmp_path / "global-skills"
    (dest / "astropy").mkdir(parents=True)
    with pytest.raises(sl.SkillLibraryError, match="already exists"):
        sl.add_skill(lib.parent, "astropy", dest, scan=_scan_ok)


def test_add_refuses_unsafe_scan(tmp_path):
    lib = _lib(tmp_path)
    dest = tmp_path / "global-skills"
    with pytest.raises(sl.SkillLibraryError, match="HIGH"):
        sl.add_skill(lib.parent, "astropy", dest, scan=lambda p: ("HIGH", "bad"))
    assert not (dest / "astropy").exists()


def test_add_refuses_when_scanner_unavailable(tmp_path):
    lib = _lib(tmp_path)
    dest = tmp_path / "global-skills"
    with pytest.raises(sl.SkillLibraryError, match="scanner"):
        sl.add_skill(lib.parent, "astropy", dest, scan=lambda p: (None, "uvx missing"))


def test_add_no_scan_records_it(tmp_path):
    lib = _lib(tmp_path)
    dest = tmp_path / "global-skills"
    out = sl.add_skill(lib.parent, "astropy", dest, scan=None,
                       commit=lambda p: ("abc", "d"), remote=lambda p: "u")
    assert "Scan: skipped (--no-scan)" in (out / "UPSTREAM").read_text()


def test_add_unknown_skill(tmp_path):
    lib = _lib(tmp_path)
    with pytest.raises(sl.SkillLibraryError, match="not found"):
        sl.add_skill(lib.parent, "nope", tmp_path / "g", scan=_scan_ok)


def test_add_rejects_path_traversal(tmp_path):
    lib = _lib(tmp_path)
    with pytest.raises(sl.SkillLibraryError):
        sl.add_skill(lib.parent, "../../etc", tmp_path / "g", scan=_scan_ok)


def test_low_severity_is_accepted():
    assert sl.scan_allows("LOW") and sl.scan_allows("SAFE") and sl.scan_allows("INFO")
    assert not sl.scan_allows("MEDIUM") and not sl.scan_allows("CRITICAL")


def test_default_library_root_is_outside_the_repo():
    assert ROOT not in sl.default_root(ROOT).parents
    assert sl.default_root(ROOT) != ROOT
