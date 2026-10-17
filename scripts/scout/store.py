"""State files for the repo scout.

Answer memory lives in scout/answers.json (tracked in git); everything transient lives in
state/ (gitignored). Every JSON write is atomic: write a .tmp, then os.replace.
"""
import datetime
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def answers(self) -> Path:
        return self.root / "scout" / "answers.json"

    @property
    def inbox(self) -> Path:
        return self.root / "scout" / "inbox.md"

    @property
    def map(self) -> Path:
        return self.root / "scout" / "map.md"

    @property
    def finds_dir(self) -> Path:
        return self.root / "scout" / "finds"

    @property
    def handoffs_dir(self) -> Path:
        return self.root / "scout" / "handoffs"

    @property
    def pending(self) -> Path:
        return self.root / "state" / "scout-pending.json"

    @property
    def queue(self) -> Path:
        return self.root / "state" / "scout-queue.json"

    @property
    def callbacks(self) -> Path:
        return self.root / "state" / "scout-callbacks.jsonl"

    @property
    def log(self) -> Path:
        return self.root / "state" / "scout.log"


def log(paths: Paths, msg: str) -> None:
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(paths.log, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def load_json(p: Path, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(p: Path, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def load_answers(p: Path) -> dict:
    data = load_json(p, None)
    if not isinstance(data, dict) or not isinstance(data.get("finds"), dict):
        return {"finds": {}}
    return data


def save_answers(p: Path, data: dict) -> None:
    save_json(p, data)


def record_answer(data: dict, repo_id: int, full_name: str, rung: int, answer: str,
                  reason, now: datetime.datetime) -> dict:
    entry = data["finds"].setdefault(str(repo_id), {})
    entry.update({
        "full_name": full_name,
        "rung": rung,
        "answer": answer,
        "reason": reason,
        "answered_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return data


def is_known(data: dict, repo_id: int) -> bool:
    return str(repo_id) in data.get("finds", {})


def read_inbox(p: Path) -> list:
    try:
        lines = Path(p).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        item = re.sub(r"^https?://github\.com/", "", item)
        item = re.sub(r"\.git$", "", item).strip("/")
        if _SLUG.match(item):
            out.append(item)
    return out


def front_matter(p: Path) -> dict:
    try:
        text = Path(p).read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def map_reviewed(p: Path) -> bool:
    return front_matter(p).get("reviewed", "").lower() == "true"
