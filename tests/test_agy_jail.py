"""features/antigravity/agy-jail: what a job can see, run for real under bubblewrap."""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import ask_agy  # noqa: E402

JAIL = REPO / "features" / "antigravity" / "agy-jail"

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None or os.name != "posix",
                                reason="needs bubblewrap")


@pytest.fixture
def box(tmp_path):
    home = tmp_path / "home"
    (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
    (home / ".gemini" / "antigravity-cli" / "settings.json").write_text("{}")
    (home / ".gemini" / "GEMINI.md").write_text("rules")
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "share" / "uv").mkdir(parents=True)
    (home / ".cache" / "uv").mkdir(parents=True)
    (home / ".cache" / "uv" / "real-cache").write_text("outside")
    (home / ".code-index").mkdir()
    (home / ".code-index" / "private.db").write_text("an index of a private repo")
    job = tmp_path / "job"
    job.mkdir()
    (job / "work.txt").write_text("JOBFILE")
    secret = tmp_path / "private"
    secret.mkdir()
    (secret / "canary.txt").write_text("TOPSECRET")
    return {"home": home, "job": job, "secret": secret, "tmp": tmp_path}


def run(box, script, job=None, **env_extra):
    env = {"HOME": str(box["home"]), "PATH": os.environ["PATH"], "TOKEN_IN_PARENT": "abc",
           "DELEGATE_LOCAL_ONLY": "", "AGY_JAIL_EXTRA": "", **env_extra}
    return subprocess.run([str(JAIL), str(job or box["job"]), "bash", "-c", script],
                          capture_output=True, text=True, env=env, timeout=60)


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                    *args], cwd=cwd, check=True, capture_output=True)


def test_job_folder_is_readable_and_writable(box):
    r = run(box, "cat work.txt && echo made > new.txt")
    assert r.returncode == 0, r.stderr
    assert "JOBFILE" in r.stdout
    assert (box["job"] / "new.txt").read_text().strip() == "made"


def test_anything_not_named_is_hidden(box):
    r = run(box, f"cat {box['secret']}/canary.txt; ls {box['tmp']}")
    assert "TOPSECRET" not in r.stdout
    assert "No such file" in r.stderr
    assert "private" not in r.stdout


def test_real_home_paths_and_docker_socket_are_hidden(box):
    paths = [".uncle-j-memory", ".claude", "backups"]
    (box["home"] / ".uncle-j-memory").mkdir()
    (box["home"] / ".claude").mkdir()
    (box["home"] / "backups").mkdir()
    checks = " ".join(f'"$HOME/{p}"' for p in paths) + " /var/run/docker.sock /run/user /opt/proj/business"
    r = run(box, f'for p in {checks}; do [ -e "$p" ] && echo "VISIBLE $p"; done; true')
    assert "VISIBLE" not in r.stdout, r.stdout


def test_caller_environment_stays_out(box):
    r = run(box, 'echo "token=[$TOKEN_IN_PARENT] bus=[$DBUS_SESSION_BUS_ADDRESS] jail=[$AGY_JAIL]"',
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus")
    assert "token=[] bus=[] jail=[1]" in r.stdout


def test_a_job_folder_under_local_only_is_refused(box):
    r = run(box, "echo RAN", DELEGATE_LOCAL_ONLY=str(box["job"]))
    assert r.returncode == 126
    assert "local-only" in r.stderr
    assert "RAN" not in r.stdout


def test_a_job_folder_inside_a_local_only_repo_is_refused(box):
    inner = box["job"] / "sub"
    inner.mkdir()
    r = run(box, "echo RAN", job=inner, DELEGATE_LOCAL_ONLY=str(box["job"]))
    assert r.returncode == 126
    assert "RAN" not in r.stdout


def test_a_git_repo_inside_a_local_only_tree_is_refused_from_a_subfolder(box):
    git(box["job"], "init", "-q")
    inner = box["job"] / "sub"
    inner.mkdir()
    r = run(box, "echo RAN", job=inner, DELEGATE_LOCAL_ONLY=str(box["job"] / "sub"))
    assert r.returncode == 126


def test_home_and_root_are_refused(box):
    for bad in (box["home"], Path("/")):
        r = run(box, "echo RAN", job=bad)
        assert r.returncode == 126, bad
        assert "RAN" not in r.stdout


def test_a_home_parent_is_refused(box):
    r = run(box, "echo RAN", job=box["tmp"])
    assert r.returncode == 126
    assert "RAN" not in r.stdout


def test_a_missing_job_folder_is_refused(box):
    r = run(box, "echo RAN", job=box["tmp"] / "gone")
    assert r.returncode != 0
    assert "RAN" not in r.stdout


def test_local_only_subfolder_inside_the_job_is_empty(box):
    private = box["job"] / "review"
    private.mkdir()
    (private / "client.md").write_text("TOPSECRET")
    (private / "client-secret.txt").write_text("TOPSECRET")   # a mask here would bring its name back
    r = run(box, "ls -A review; cat review/client.md", DELEGATE_LOCAL_ONLY=str(private))
    assert "TOPSECRET" not in r.stdout
    assert "client" not in r.stdout
    assert (private / "client.md").read_text() == "TOPSECRET"


@pytest.mark.parametrize("name", [".env", ".env.local", "prod.env", "id_rsa", "id_ed25519.pub",
                                  "aws_creds.json", "CREDENTIALS", "my-secret.txt", "deep/.env"])
def test_secret_named_files_read_empty(box, name):
    f = box["job"] / name
    f.parent.mkdir(exist_ok=True)
    f.write_text("TOPSECRET")
    r = run(box, f"cat {name}")
    assert r.returncode == 0
    assert "TOPSECRET" not in r.stdout
    assert f.read_text() == "TOPSECRET"


def test_agy_rules_are_read_only_and_its_state_is_writable(box):
    settings = box["home"] / ".gemini" / "antigravity-cli" / "settings.json"
    r = run(box, 'echo x > "$HOME/.gemini/antigravity-cli/settings.json"; '
                 'echo x > "$HOME/.gemini/GEMINI.md"; '
                 'echo y > "$HOME/.gemini/antigravity-cli/state" && echo state-ok')
    assert settings.read_text() == "{}"
    assert (box["home"] / ".gemini" / "GEMINI.md").read_text() == "rules"
    assert "state-ok" in r.stdout
    assert (box["home"] / ".gemini" / "antigravity-cli" / "state").read_text().strip() == "y"


def test_caches_and_indexes_are_private_to_jobs(box):
    r = run(box, 'ls -A "$HOME/.cache/uv" "$HOME/.code-index"; echo poison > "$HOME/.cache/uv/planted"')
    assert r.returncode == 0, r.stderr
    assert "real-cache" not in r.stdout
    assert "private.db" not in r.stdout
    assert not (box["home"] / ".cache" / "uv" / "planted").exists()
    assert (box["home"] / ".local" / "state" / "agy-jail" / "uv-cache" / "planted").exists()


def test_tools_are_read_only(box):
    r = run(box, 'touch "$HOME/.local/bin/planted" /usr/planted; echo done')
    assert "done" in r.stdout
    assert not (box["home"] / ".local" / "bin" / "planted").exists()


def test_git_works_in_a_linked_worktree_and_its_hooks_are_read_only(box):
    main = box["job"]
    git(main, "init", "-q")
    git(main, "add", ".")
    git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first")
    wt = box["tmp"] / "wt"
    git(main, "worktree", "add", "-q", str(wt), "-b", "side")
    hooks = main / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    r = run(box, f"git status -s >/dev/null && echo git-ok; cat work.txt; "
                 f"echo evil > {hooks}/pre-commit; echo tried", job=wt)
    assert "git-ok" in r.stdout, r.stderr
    assert "JOBFILE" in r.stdout
    assert "tried" in r.stdout
    assert not (hooks / "pre-commit").exists()


def test_extra_paths_are_read_only_and_never_override_local_only(box):
    extra = box["tmp"] / "extra"
    extra.mkdir()
    (extra / "game.txt").write_text("GAMEFILE")
    r = run(box, f"cat {extra}/game.txt; touch {extra}/planted; cat {box['secret']}/canary.txt",
            AGY_JAIL_EXTRA=f"{extra}:{box['secret']}", DELEGATE_LOCAL_ONLY=str(box["secret"]))
    assert "GAMEFILE" in r.stdout
    assert not (extra / "planted").exists()
    assert "TOPSECRET" not in r.stdout
    assert "skipping extra" in r.stderr


def test_the_private_list_being_missing_refuses(box, tmp_path):
    copy = tmp_path / "copy" / "features" / "antigravity"
    copy.mkdir(parents=True)
    shutil.copy(JAIL, copy / "agy-jail")
    os.chmod(copy / "agy-jail", os.stat(copy / "agy-jail").st_mode | stat.S_IEXEC)
    r = subprocess.run([str(copy / "agy-jail"), str(box["job"]), "echo", "RAN"], capture_output=True,
                       text=True, env={"HOME": str(box["home"]), "PATH": os.environ["PATH"]})
    assert r.returncode == 126
    assert "RAN" not in r.stdout


def test_the_shipped_private_list_covers_the_known_paths():
    text = (REPO / "config" / "delegate-local-only.txt").read_text()
    for path in ("/opt/proj/anatomy-lab", "/opt/proj/business", "/opt/proj/Uncle-J-s-Refinery/review"):
        assert path in text


def fake_agy(tmp_path, body='{"event":"result","result":{"status":"SUCCESS","response":"ok"}}'):
    script = tmp_path / "fakeagy"
    script.write_text(f"#!/bin/sh\necho \"$AGY_JAIL\" > jail-seen\necho '{body}'\n")
    script.chmod(0o755)
    return script


def test_ask_runs_jobs_in_the_jail(box, monkeypatch):
    monkeypatch.setenv("HOME", str(box["home"]))
    monkeypatch.setenv("AGY_BIN", str(fake_agy(box["tmp"])))
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")
    out = ask_agy.ask("hi", cwd=str(box["job"]))
    assert out["ok"], out
    assert (box["job"] / "jail-seen").read_text().strip() == "1"


def test_ask_reports_a_refusal_and_never_runs_agy(box, monkeypatch):
    monkeypatch.setenv("HOME", str(box["home"]))
    monkeypatch.setenv("AGY_BIN", str(fake_agy(box["tmp"])))
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", str(box["job"]))
    out = ask_agy.ask("hi", cwd=str(box["job"]))
    assert not out["ok"]
    assert "local-only" in json.dumps(out)
    assert not (box["job"] / "jail-seen").exists()


def test_ask_refuses_when_bwrap_is_missing(box, monkeypatch):
    monkeypatch.setenv("AGY_BIN", str(fake_agy(box["tmp"])))
    monkeypatch.setattr(ask_agy.shutil, "which", lambda name, **kw: None if name == "bwrap" else str(box["tmp"] / "fakeagy"))
    out = ask_agy.ask("hi", cwd=str(box["job"]))
    assert out["error"] == "agy_jail_unavailable"
    assert not (box["job"] / "jail-seen").exists()


def test_ask_names_the_login_command_when_jobs_are_logged_out(box, monkeypatch):
    agy = box["tmp"] / "fakeagy"
    agy.write_text("#!/bin/sh\necho 'Error: authentication required.' >&2\nexit 1\n")
    agy.chmod(0o755)
    monkeypatch.setenv("HOME", str(box["home"]))
    monkeypatch.setenv("AGY_BIN", str(agy))
    monkeypatch.setenv("DELEGATE_LOCAL_ONLY", "")
    out = ask_agy.ask("hi", cwd=str(box["job"]))
    assert not out["ok"]
    assert "just agy-login" in out.get("hint", "")
