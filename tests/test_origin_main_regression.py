"""
Behaviour matrix for scripts/check-origin-main-regression.sh.

The detector exists because origin/main was force-reset five times without anyone
noticing (PRs #100-#105 destroyed; see the script header). It must fire on a
non-fast-forward regression and stay silent on everything else -- a detector that
cries wolf gets ignored, which is the same outcome as not having one.

Every case drives a REAL bare repo as `origin`, so `git ls-remote`, `cat-file -e`
and `merge-base --is-ancestor` all execute for real. There is no injection seam
faking the remote, because the bug class being defended against is precisely
"the thing you asked disagreed with the actual remote".
"""
import os
import subprocess

import pytest

SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "check-origin-main-regression.sh"
)


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )


@pytest.fixture()
def repo(tmp_path):
    """A clone whose `origin` is a local bare repo we can rewrite at will."""
    bare = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True,
                   capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True,
                   capture_output=True)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    _git(work, "remote", "add", "origin", str(bare))

    shas = []
    for n in range(3):
        (work / f"f{n}.txt").write_text(str(n))
        _git(work, "add", "-A")
        _git(work, "commit", "-m", f"c{n}")
        shas.append(_git(work, "rev-parse", "HEAD").stdout.strip())
    _git(work, "push", "-q", "origin", "main")
    return {"work": work, "bare": bare, "shas": shas,
            "seen": tmp_path / "seen.sha", "log": tmp_path / "reg.log"}


def _run(repo, allow_stderr=False):
    env = {
        **os.environ,
        "ORIGIN_MAIN_SEEN_FILE": str(repo["seen"]),
        "ORIGIN_MAIN_REG_LOG": str(repo["log"]),
    }
    r = subprocess.run(["bash", SCRIPT, str(repo["work"])], env=env,
                       capture_output=True, text=True)
    # The caller folds stderr into the session banner (`REG_OUT=$(... 2>&1)`), so
    # any stray shell noise becomes a scary-looking startup message. Asserted on
    # every call, not in one dedicated test, because the first regression here was
    # a missing-file read that only ever showed up on a fresh clone.
    if not allow_stderr:
        assert r.stderr == "", f"unexpected stderr: {r.stderr!r}"
    return r.returncode, r.stdout.strip()


def _force_remote_to(repo, sha):
    """Rewind the remote -- exactly what the second clone kept doing to main."""
    _git(repo["work"], "push", "-q", "--force", "origin", f"{sha}:refs/heads/main")


# ── the case this exists for ────────────────────────────────────────────────

def test_detects_non_fast_forward_regression(repo):
    rc, out = _run(repo)
    assert rc == 0 and out.startswith("BASELINE"), out

    _force_remote_to(repo, repo["shas"][0])  # drop 2 merged commits
    rc, out = _run(repo)

    assert rc == 1, f"regression must be reported via exit code, got {rc}: {out}"
    assert "went BACKWARDS" in out
    assert "2 commit(s) dropped" in out, out
    assert "REGRESSED" in repo["log"].read_text()


def test_regression_names_the_recovery_constraint(repo):
    """A `reset --hard` here would destroy local-only commits -- 3f70ec2 was one."""
    _run(repo)
    _force_remote_to(repo, repo["shas"][0])
    _, out = _run(repo)
    assert "never `reset --hard`" in out, out


def test_regression_reported_once_then_rebaselines(repo):
    """Alert on the event, not forever after -- a permanent alarm is noise."""
    _run(repo)
    _force_remote_to(repo, repo["shas"][0])
    assert _run(repo)[0] == 1
    rc, out = _run(repo)
    assert rc == 0 and out.startswith("OK unchanged"), out


# ── must stay silent: false positives strangle the signal ───────────────────

def test_first_run_adopts_baseline(repo):
    rc, out = _run(repo)
    assert rc == 0 and out.startswith("BASELINE")
    assert repo["seen"].read_text().strip() == repo["shas"][2]


def test_unchanged_remote_is_quiet(repo):
    _run(repo)
    rc, out = _run(repo)
    assert rc == 0 and out.startswith("OK unchanged")


def test_fast_forward_advance_is_not_a_regression(repo):
    """The common case: work lands normally. Must never alarm."""
    _run(repo)
    (repo["work"] / "new.txt").write_text("x")
    _git(repo["work"], "add", "-A")
    _git(repo["work"], "commit", "-m", "c3")
    _git(repo["work"], "push", "-q", "origin", "main")

    rc, out = _run(repo)
    assert rc == 0 and out.startswith("OK advanced"), out
    assert repo["seen"].read_text().strip() == _git(
        repo["work"], "rev-parse", "HEAD").stdout.strip()


def test_local_ahead_of_remote_is_not_a_regression(repo):
    """Unpushed local work is normal -- 'local ahead' is the WRONG signal to use."""
    _run(repo)
    (repo["work"] / "unpushed.txt").write_text("x")
    _git(repo["work"], "add", "-A")
    _git(repo["work"], "commit", "-m", "unpushed")

    rc, out = _run(repo)
    assert rc == 0 and out.startswith("OK unchanged"), out


# ── degraded conditions must not fabricate an incident ──────────────────────

def test_unreachable_remote_skips_without_touching_the_stamp(repo):
    """Offline/auth failure must be silence, not a false regression report."""
    _run(repo)
    baseline = repo["seen"].read_text()
    _git(repo["work"], "remote", "set-url", "origin",
         str(repo["bare"]) + "-does-not-exist")

    rc, out = _run(repo)
    assert rc == 0 and out.startswith("SKIP ls-remote-empty"), out
    assert repo["seen"].read_text() == baseline, "stamp must survive a failed check"


def test_no_origin_remote_skips(repo):
    _git(repo["work"], "remote", "remove", "origin")
    rc, out = _run(repo)
    assert rc == 0 and out.startswith("SKIP no-origin-remote"), out


def test_unjudgeable_baseline_is_logged_not_swallowed(repo):
    """
    A baseline absent from this clone cannot be compared. That is also what a
    force-push whose dropped commits were never fetched looks like, so the gap
    must leave an audit trail rather than pass quietly.
    """
    _run(repo)
    repo["seen"].write_text("0" * 40 + "\n")

    rc, out = _run(repo)
    assert rc == 0 and out.startswith("CANNOT-COMPARE"), out
    assert "cannot-compare" in repo["log"].read_text()
    assert repo["seen"].read_text().strip() == repo["shas"][2]
