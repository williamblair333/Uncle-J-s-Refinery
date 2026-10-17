"""GitHub facts for the scout, read only through `gh api`.

Every star count, licence, date and URL a message shows comes from here, never from a model.
Each function takes a `run` callable so tests can feed canned responses.
"""
import json
import subprocess
import time
from dataclasses import dataclass, field

README_CAP = 20000
SEARCH_INTERVAL = 2.1  # seconds; GitHub allows 30 authenticated searches a minute
_clock = time.monotonic
_sleep = time.sleep
_last_search = 0.0


@dataclass
class Facts:
    id: int
    full_name: str
    html_url: str
    description: str
    stars: int
    license: str | None
    pushed_at: str
    archived: bool
    fork: bool
    topics: list = field(default_factory=list)


def _gh(args: list) -> tuple:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, r.stdout


def _facts(d: dict) -> Facts:
    lic = d.get("license") or {}
    return Facts(
        id=int(d["id"]),
        full_name=d["full_name"],
        html_url=d.get("html_url", ""),
        description=d.get("description") or "",
        stars=int(d.get("stargazers_count", 0)),
        license=lic.get("spdx_id") if isinstance(lic, dict) else None,
        pushed_at=d.get("pushed_at") or "",
        archived=bool(d.get("archived")),
        fork=bool(d.get("fork")),
        topics=list(d.get("topics") or []),
    )


def repo_facts(full_name: str, run=_gh):
    rc, out = run(["api", f"repos/{full_name}"])
    if rc != 0:
        return None
    try:
        return _facts(json.loads(out))
    except (ValueError, KeyError, TypeError):
        return None


def _pace() -> None:
    """Keep real searches under GitHub's 30-a-minute search limit."""
    global _last_search
    wait = SEARCH_INTERVAL - (_clock() - _last_search)
    if wait > 0:
        _sleep(wait)
    _last_search = _clock()


def search_checked(query: str, limit: int = 10, run=None):
    """Search repositories. Returns None when the search itself failed (rate limit,
    network, auth), so callers can tell "nothing found" from "couldn't look"."""
    if run is None:
        _pace()
        run = _gh
    rc, out = run(["api", "-X", "GET", "search/repositories",
                   "-f", f"q={query}", "-f", "sort=stars", "-f", f"per_page={limit}"])
    if rc != 0:
        return None
    try:
        items = json.loads(out).get("items", [])
        facts = [_facts(i) for i in items]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return [f for f in facts if not f.archived and not f.fork]


def search(query: str, limit: int = 10, run=None) -> list:
    return search_checked(query, limit, run) or []


def readme(full_name: str, run=_gh) -> str:
    rc, out = run(["api", f"repos/{full_name}/readme",
                   "-H", "Accept: application/vnd.github.raw"])
    if rc != 0:
        return ""
    return out[:README_CAP]
