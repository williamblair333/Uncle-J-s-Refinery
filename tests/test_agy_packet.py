"""Tests for ask_agy_packet: named files leave a local-only repo only when allow-listed, in a
throwaway copy, and come back as a diff. No network, agy or quota is used."""
import fnmatch
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent


def load():
    spec = importlib.util.spec_from_file_location("delegate_server_packet", REPO / "scripts/delegate/server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = load()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "business"
    (root / "tools").mkdir(parents=True)
    (root / "clients" / "acme").mkdir(parents=True)
    (root / "tools" / "a.py").write_text("x = 1\n")
    (root / "tools" / "b.py").write_text("y = 2\n")
    (root / "clients" / "acme" / "notes.md").write_text("private\n")
    allow = tmp_path / "allow.txt"
    allow.write_text(f"{root / 'tools'}   # generic code\n")
    monkeypatch.setattr(d, "PACKET_ALLOW_FILE", allow)
    monkeypatch.setattr(d, "PACKET_ALLOW_LOCAL_FILE", tmp_path / "no-local.txt")
    (root / "private").mkdir()
    (root / "private" / "packet-refuse-words.txt").write_text("# people and sites\nAcme Fire  # a client\n")
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", str(root))
    monkeypatch.setattr(d, "PACKET_ROOT", tmp_path / "packets")
    monkeypatch.setattr(d, "LOG_PATH", None)
    routing = tmp_path / "routing.json"
    routing.write_text(json.dumps({"default": "code", "tiers": {"code": ["gemini-3.8-flash-medium"]}}))
    monkeypatch.setattr(d, "ROUTING_FILE", routing)
    return root


def agent(change=None, ok=True, seen=None):
    """A stand-in for ask_agy.ask that records what it can see, then edits the copy."""
    def ask(prompt, cwd=None, edits=False, timeout=None, model=None):
        here = Path(cwd)
        if seen is not None:
            seen["cwd"] = here
            seen["edits"] = edits
            seen["files"] = sorted(str(p.relative_to(here)) for p in here.rglob("*") if p.is_file())
        if change:
            change(here)
        return {"ok": ok, "response": "DONE"}
    return ask


def never(_here):
    pytest.fail("agy ran")


def run(root, files, prompt="fix it", **kw):
    return d.run_agy_packet(prompt, files, str(root), **kw)


def test_only_named_files_are_copied(repo):
    seen = {}
    out = run(repo, ["tools/a.py"], ask=agent(seen=seen))
    assert out["ok"], out
    assert seen["files"] == ["tools/a.py"]
    assert seen["edits"] is True
    assert seen["cwd"].resolve() != repo.resolve()


def test_returns_diff_and_leaves_live_files_alone(repo):
    def edit(here):
        (here / "tools" / "a.py").write_text("x = 3\n")
        (here / "tools" / "new.py").write_text("z = 1\n")
    out = run(repo, ["tools/a.py"], ask=agent(edit))
    assert (repo / "tools" / "a.py").read_text() == "x = 1\n"
    assert not (repo / "tools" / "new.py").exists()
    assert "-x = 1" in out["diff"] and "+x = 3" in out["diff"]
    assert "+z = 1" in out["diff"]
    assert out["changed"] == ["tools/a.py", "tools/new.py"]


def test_deleted_file_shows_in_diff(repo):
    out = run(repo, ["tools/a.py"], ask=agent(lambda h: (h / "tools" / "a.py").unlink()))
    assert "-x = 1" in out["diff"] and out["changed"] == ["tools/a.py"]


def test_a_symlink_made_by_the_agent_isnt_followed(repo):
    out = run(repo, ["tools/a.py"],
              ask=agent(lambda h: (h / "tools" / "peek").symlink_to(repo / "clients" / "acme" / "notes.md")))
    assert "private" not in out["diff"]
    assert out["changed"] == ["tools/peek"] and "symlink to" in out["diff"]


def test_a_file_containing_a_listed_name_is_refused(repo):
    (repo / "tools" / "c.py").write_text("# for the acme FIRE station\n")
    out = run(repo, ["tools/a.py", "tools/c.py"], ask=agent(never))
    assert out["error"] == "names_hit" and "tools/c.py" in out["detail"]


def test_a_file_named_after_a_listed_name_is_refused(repo):
    (repo / "tools" / "acme fire.py").write_text("x = 1\n")
    assert run(repo, ["tools/acme fire.py"], ask=agent(never))["error"] == "names_hit"


def test_a_prompt_containing_a_listed_name_is_refused(repo):
    assert run(repo, ["tools/a.py"], prompt="fix this for Acme Fire", ask=agent(never))["error"] == "names_hit"


@pytest.mark.parametrize("text", [None, "", "# only a comment\n\n"])
def test_no_names_to_check_means_refused(repo, text):
    words = repo / "private" / "packet-refuse-words.txt"
    words.unlink()
    if text is not None:
        words.write_text(text)
    assert run(repo, ["tools/a.py"], ask=agent(never))["error"] == "no_names_list"


def test_a_file_the_scan_cant_read_is_refused(repo):
    (repo / "tools" / "blob").write_bytes(b"\x80\x81\x82")
    assert run(repo, ["tools/blob"], ask=agent(never))["error"] == "not_text"
    (repo / "tools" / "wide.txt").write_text("Acme Fire\n", encoding="utf-16")  # hides the name from a byte scan
    assert run(repo, ["tools/wide.txt"], ask=agent(never))["error"] == "not_text"


def test_the_local_allow_list_counts(repo, monkeypatch, tmp_path):
    (repo / "docs").mkdir()
    (repo / "docs" / "d.md").write_text("hi\n")
    assert run(repo, ["docs/d.md"], ask=agent(never))["error"] == "not_allow_listed"
    local = tmp_path / "local.txt"
    local.write_text(f"{repo / 'docs' / 'd.md'}\n")
    monkeypatch.setattr(d, "PACKET_ALLOW_LOCAL_FILE", local)
    assert run(repo, ["docs/d.md"], ask=agent())["ok"]


def test_binary_edit_is_reported(repo):
    (repo / "tools" / "blob").write_text("text\n")
    out = run(repo, ["tools/blob"], ask=agent(lambda h: (h / "tools" / "blob").write_bytes(b"\x90\x91\x92")))
    assert out["changed"] == ["tools/blob"] and "Binary file tools/blob differs" in out["diff"]


def test_line_ending_edit_is_reported(repo):
    (repo / "tools" / "dos.txt").write_bytes(b"one\r\n")
    out = run(repo, ["tools/dos.txt"], ask=agent(lambda h: (h / "tools" / "dos.txt").write_bytes(b"one\n")))
    assert out["changed"] == ["tools/dos.txt"]


def test_copy_keeps_exact_bytes(repo):
    (repo / "tools" / "dos.txt").write_bytes(b"caf\xc3\xa9\r\n")
    got = {}
    run(repo, ["tools/dos.txt"], ask=agent(lambda h: got.update(data=(h / "tools" / "dos.txt").read_bytes())))
    assert got["data"] == b"caf\xc3\xa9\r\n"


def test_an_unreadable_file_doesnt_lose_the_result(repo):
    def edit(here):
        (here / "tools" / "a.py").write_text("x = 3\n")
        (here / "tools" / "locked").write_text("no\n")
        (here / "tools" / "locked").chmod(0)
    out = run(repo, ["tools/a.py"], ask=agent(edit))
    assert "+x = 3" in out["diff"] and "tools/locked" in out["changed"]


@pytest.mark.parametrize("name", ["tools/a\0.py", "tools/" + "a" * 5000])
def test_bad_names_refuse_without_raising(repo, name):
    # Python versions differ on whether a long name raises or just isn't found. Either way it's refused.
    assert run(repo, [name], ask=agent(never))["error"] in ("not_allow_listed", "file_not_found")


@pytest.mark.parametrize("text", [None, "{not json", "[]"])
def test_no_readable_deny_rules_means_refused(repo, monkeypatch, tmp_path, text):
    rules = tmp_path / "permissions.json"
    if text is not None:
        rules.write_text(text)
    monkeypatch.setattr(d, "PERMISSIONS_FILE", rules)
    assert run(repo, ["tools/a.py"], ask=agent(never))["error"] == "deny_rules_unreadable"


def test_unusable_packet_root_refuses_without_raising(repo, monkeypatch, tmp_path):
    (tmp_path / "file").write_text("in the way\n")
    monkeypatch.setattr(d, "PACKET_ROOT", tmp_path / "file" / "packets")
    assert run(repo, ["tools/a.py"], ask=agent(never))["error"] == "packet_root_unusable"


def test_a_symlink_swapped_in_after_the_check_isnt_read(repo):
    (repo / "tools" / "link").symlink_to(repo / "clients" / "acme" / "notes.md")
    with pytest.raises(OSError):
        d._read_no_follow(repo / "tools" / "link")


def test_copy_is_removed_afterward(repo):
    seen = {}
    run(repo, ["tools/a.py"], ask=agent(seen=seen))
    assert not seen["cwd"].exists()


@pytest.mark.parametrize("name", ["clients/acme/notes.md", "tools/../clients/acme/notes.md"])
def test_refuses_a_file_outside_the_allow_list(repo, name):
    assert run(repo, [name], ask=agent(never))["error"] == "not_allow_listed"


def test_one_bad_file_refuses_the_whole_packet(repo):
    out = run(repo, ["tools/a.py", "clients/acme/notes.md"], ask=agent(never))
    assert out["error"] == "not_allow_listed"


def test_refuses_a_symlink_that_escapes(repo):
    (repo / "tools" / "link.py").symlink_to(repo / "clients" / "acme" / "notes.md")
    assert run(repo, ["tools/link.py"], ask=agent(never))["error"] == "not_allow_listed"


def test_refuses_absolute_and_escaping_names(repo, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("no\n")
    for name in (str(outside), "../outside.py"):
        assert run(repo, [name], ask=agent(never))["error"] == "not_allow_listed"


def test_secret_shaped_name_refused_even_when_listed(repo):
    (repo / "tools" / "my-secret.py").write_text("k = 1\n")
    assert run(repo, ["tools/my-secret.py"], ask=agent(never))["error"] == "not_allow_listed"


def test_missing_file_and_empty_list(repo):
    assert run(repo, ["tools/gone.py"], ask=agent(never))["error"] == "file_not_found"
    assert run(repo, [], ask=agent(never))["error"] == "no_files"


def test_size_cap(repo, monkeypatch):
    monkeypatch.setattr(d, "PACKET_MAX_BYTES", 3)
    assert run(repo, ["tools/a.py"], ask=agent(never))["error"] == "packet_too_large"


def test_no_allow_list_means_refused(repo, monkeypatch, tmp_path):
    monkeypatch.setattr(d, "PACKET_ALLOW_FILE", tmp_path / "missing.txt")
    assert run(repo, ["tools/a.py"], ask=agent(never))["error"] == "not_allow_listed"


def test_prompt_naming_a_local_only_path_is_refused(repo):
    out = run(repo, ["tools/a.py"], prompt=f"also read {repo}/clients/acme/notes.md", ask=agent(never))
    assert out["error"] == "local_only"


def test_a_failed_run_still_reports_what_changed(repo):
    out = run(repo, ["tools/a.py"], ask=agent(lambda h: (h / "tools" / "a.py").write_text("x = 9\n"), ok=False))
    assert out["ok"] is False and "+x = 9" in out["diff"]


def test_a_whole_local_only_repo_is_never_allow_listed():
    roots = set(d.local_only_roots(d.LOCAL_ONLY_FILE, env=""))
    for allow in (d.PACKET_ALLOW_FILE, d.PACKET_ALLOW_LOCAL_FILE):
        assert not set(d.local_only_roots(allow, env="")) & roots


def test_the_public_allow_list_stays_empty_of_private_paths():
    assert d.local_only_roots(d.PACKET_ALLOW_FILE, env="") == []


def test_every_local_only_path_is_denied_to_agy_directly():
    """The delegate guard only sees the prompt. Without a deny rule, agy can read the path itself."""
    deny = json.loads((REPO / "features/antigravity/permissions.json").read_text())["deny"]
    rules = [r[len("read_file("):-1].rstrip("/") for r in deny if r.startswith("read_file(")]
    for raw in (REPO / "config/delegate-local-only.txt").read_text().splitlines():
        path = raw.split("#", 1)[0].strip().rstrip("/")
        if path:
            assert any(fnmatch.fnmatch(path, rule) for rule in rules), f"{path} is local-only, but agy may read it"
