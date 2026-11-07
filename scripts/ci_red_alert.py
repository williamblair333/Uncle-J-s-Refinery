#!/usr/bin/env python3
"""Alert Bill when GitHub Actions CI on main goes red."""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UNREADABLE_MESSAGE = "can't read CI"
UNREADABLE_THRESHOLD_SECONDS = 24 * 3600
CRON_TAG = "uncle-j-ci-red-alert"
REPO_ROOT = Path(__file__).resolve().parent.parent


def fetch_latest_run(timeout: int = 60) -> dict | None:
    """Fetch latest CI workflow run on main from GitHub using gh CLI."""
    cmd = [
        "gh",
        "run",
        "list",
        "--branch",
        "main",
        "--workflow",
        "CI",
        "--limit",
        "1",
        "--json",
        "databaseId,conclusion,status,displayTitle,url",
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
            cwd=REPO_ROOT,  # cron starts in $HOME, where gh has no repo to read
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout)
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return data[0]
        return None
    except Exception:
        return None


def format_run_message(run: dict) -> str:
    """Format run alert message containing only conclusion, displayTitle and url."""
    conclusion = run.get("conclusion") or ""
    title = run.get("displayTitle") or ""
    url = run.get("url") or ""
    return f"{conclusion}: {title}\n{url}"


def decide(run_or_none: dict | None, state: dict, now: float | None = None) -> tuple[str | None, dict]:
    """Decide what message to send and compute new state.

    - run_or_none is None if gh failed, timed out, returned invalid JSON or empty list.
    - state is the persisted state dict.
    - now is current timestamp in seconds.
    """
    if now is None:
        now = time.time()

    new_state = dict(state)

    if run_or_none is None:
        first_unreadable = new_state.get("first_unreadable_at")
        if first_unreadable is None:
            new_state["first_unreadable_at"] = now
            return None, new_state

        if (now - first_unreadable) >= UNREADABLE_THRESHOLD_SECONDS:
            if not new_state.get("unreadable_alert_sent"):
                new_state["unreadable_alert_sent"] = True
                return UNREADABLE_MESSAGE, new_state
        return None, new_state

    # Successfully read a run from gh: clear unreadable tracking
    new_state.pop("first_unreadable_at", None)
    new_state.pop("unreadable_alert_sent", None)

    status = run_or_none.get("status")
    if status != "completed":
        return None, new_state

    conclusion = run_or_none.get("conclusion")
    run_id = run_or_none.get("databaseId")

    if conclusion == "success":
        if new_state.get("last_red_id") is not None:
            new_state.pop("last_red_id", None)
            return format_run_message(run_or_none), new_state
        return None, new_state

    # Any other completed conclusion (failure, timed_out, cancelled, etc.)
    last_red_id = new_state.get("last_red_id")
    if run_id is not None and run_id != last_red_id:
        new_state["last_red_id"] = run_id
        return format_run_message(run_or_none), new_state

    return None, new_state


def load_state(path: Path) -> dict:
    """Load state from json file. Missing or corrupt files return empty dict."""
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except Exception:
        return {}


def save_state(path: Path, state: dict) -> None:
    """Atomically write state dict to file using temp file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def telegram_credentials(repo_root: Path, environ=os.environ) -> tuple[str, str]:
    """Token and chat id from the environment, else repo .env: cron passes neither."""
    values = {k: environ[k] for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if environ.get(k)}
    env_file = repo_root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.removeprefix("export ").partition("=")
            if sep and key.strip() in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
                values.setdefault(key.strip(), value.strip().strip("'\""))
    if len(values) != 2:
        raise RuntimeError("Telegram credentials missing")
    return values["TELEGRAM_BOT_TOKEN"], values["TELEGRAM_CHAT_ID"]


def send_notification(repo_root: Path, message: str, urlopen=urllib.request.urlopen) -> None:
    """Post to Telegram and check its reply, so a failed send leaves state unchanged for a retry.

    Not lib/notify.sh: _tg_send_text swallows curl's exit status, and its HTML parse mode rejects
    a run title containing `<`. Errors are reduced to their type: urllib's text holds the URL,
    which holds the token.
    """
    token, chat_id = telegram_credentials(repo_root)
    body = json.dumps({"chat_id": chat_id, "text": f"CI on main: {message}"}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            reply = json.load(response)
    except Exception as exc:
        raise RuntimeError(f"Telegram request failed: {type(exc).__name__}") from None
    if not reply.get("ok"):
        raise RuntimeError(f"Telegram refused the message: {reply.get('description')}")


def with_cron_line(crontab: str, repo_root: Path) -> str:
    """The crontab with this job added once. dma64 only, so hosts don't each send the alert."""
    if CRON_TAG in crontab:
        return crontab
    line = (
        f"*/15 * * * * PATH=/usr/local/bin:/usr/bin:/bin python3 {repo_root}/scripts/ci_red_alert.py "
        f">> {repo_root}/state/ci-red-alert.log 2>&1 # {CRON_TAG}"
    )
    return (crontab.rstrip("\n") + "\n" if crontab.strip() else "") + line + "\n"


def install_cron(repo_root: Path) -> int:
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if current.returncode != 0 and "no crontab" not in current.stderr:
        sys.stderr.write(f"can't read crontab: {current.stderr}\n")
        return 1
    updated = with_cron_line(current.stdout, repo_root)
    if updated == current.stdout:
        print("already installed")
        return 0
    subprocess.run(["crontab", "-"], input=updated, text=True, check=True)
    print("installed")
    return 0


def main(
    argv: list[str] | None = None,
    repo_root: Path | None = None,
    fetch_fn=None,
    send_fn=None,
    now_fn=None,
) -> int:
    parser = argparse.ArgumentParser(description="Alert Bill when GitHub Actions CI on main goes red.")
    parser.add_argument("--dry-run", action="store_true", help="Print message instead of sending and do not write state")
    parser.add_argument("--install-cron", action="store_true", help="Add the 15-minute cron job on this host")
    args = parser.parse_args(argv)

    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    if args.install_cron:
        return install_cron(repo_root)
    state_file = repo_root / "state" / "ci-red-alert.json"

    state = load_state(state_file)
    run_or_none = fetch_fn() if fetch_fn is not None else fetch_latest_run()
    now = now_fn() if now_fn is not None else time.time()

    message, new_state = decide(run_or_none, state, now)

    if args.dry_run:
        if message:
            print(message)
        return 0

    if message:
        try:
            if send_fn is not None:
                send_fn(repo_root, message)
            else:
                send_notification(repo_root, message)
        except Exception as e:
            sys.stderr.write(f"Error sending notification: {e}\n")
            return 1

    save_state(state_file, new_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
