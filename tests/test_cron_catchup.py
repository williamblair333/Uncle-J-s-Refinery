"""cron_catchup: crontab parsing, which jobs fall in a downtime gap, state handling."""
import subprocess
from datetime import datetime

from scripts import cron_catchup
from scripts.cron_catchup import due_in, missed_jobs, parse_crontab, repo_busy

CRONTAB = """\
# uncle-j-telegram-gateway
*/2 * * * * bash poll.sh >> poll.log 2>&1
# uncle-j-session-stats
0 8 * * 0 bash stats.sh >> stats.log 2>&1
# uncle-j-jcodemunch-reindex
0 1 * * * bash reindex.sh >> reindex.log 2>&1
20 2 * * * /opt/backup.sh >> backup.log 2>&1 # gitea-backup
0 * * * * bash hourly.sh
@reboot sleep 120 && python3 cron_catchup.py
SHELL=/bin/bash
# uncle-j-repo-scout
15 4 * * * python3 run.py run >> scout.log 2>&1
"""


def test_parse_keeps_fixed_time_jobs_only():
    names = [j.name for j in parse_crontab(CRONTAB)]
    assert names == ["uncle-j-session-stats", "uncle-j-jcodemunch-reindex",
                     "gitea-backup", "uncle-j-repo-scout"]


def test_parse_keeps_full_command():
    job = next(j for j in parse_crontab(CRONTAB) if j.name == "uncle-j-repo-scout")
    assert job.command == "python3 run.py run >> scout.log 2>&1"


def test_overnight_gap_runs_nightly_jobs_in_schedule_order():
    # 2026-10-17 22:09 (Sat) -> 2026-10-18 08:06 (Sun): stats due Sun 08:00 is in.
    gap = (datetime(2026, 10, 17, 22, 9), datetime(2026, 10, 18, 8, 6))
    order = [j.name for _, j in missed_jobs(parse_crontab(CRONTAB), *gap)]
    assert order == ["uncle-j-jcodemunch-reindex", "gitea-backup",
                     "uncle-j-repo-scout", "uncle-j-session-stats"]


def test_weekly_job_skipped_on_other_days():
    stats = next(j for j in parse_crontab(CRONTAB) if j.name == "uncle-j-session-stats")
    # Fri 22:00 -> Sat 09:00: no Sunday in the gap.
    assert due_in(stats, datetime(2026, 10, 16, 22), datetime(2026, 10, 17, 9)) is None


def test_job_that_ran_before_shutdown_is_not_rerun():
    reindex = next(j for j in parse_crontab(CRONTAB) if j.name == "uncle-j-jcodemunch-reindex")
    # Up until 01:30, back at 07:00: the 01:00 run happened.
    assert due_in(reindex, datetime(2026, 10, 18, 1, 30), datetime(2026, 10, 18, 7)) is None


def test_multi_day_gap_runs_each_job_once():
    gap = (datetime(2026, 10, 10, 23), datetime(2026, 10, 18, 9))
    names = [j.name for _, j in missed_jobs(parse_crontab(CRONTAB), *gap)]
    assert len(names) == len(set(names)) == 4


def test_dow_seven_is_sunday():
    job = parse_crontab("0 8 * * 7 bash x.sh\n")[0]
    assert job.dows == (0,)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_repo_busy_only_when_off_main_or_dirty(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f").write_text("a")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    assert repo_busy(tmp_path) is None
    (tmp_path / "f").write_text("b")
    assert repo_busy(tmp_path) == "uncommitted changes"
    _git(tmp_path, "checkout", "-q", "--", "f")
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    assert repo_busy(tmp_path) == "on branch feat"


def test_corrupt_state_reads_as_not_done(tmp_path, monkeypatch):
    state = tmp_path / "cron-catchup.json"
    state.write_text('{"boot_id": "ab')
    monkeypatch.setattr(cron_catchup, "STATE", state)
    assert cron_catchup.read_state() == {}
    cron_catchup.write_state({"boot_id": "x"})
    assert cron_catchup.read_state() == {"boot_id": "x"}
