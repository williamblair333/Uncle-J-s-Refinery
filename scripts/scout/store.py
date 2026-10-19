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
    def rotation(self) -> Path:
        return self.root / "state" / "scout-rotation.json"

    @property
    def top100(self) -> Path:
        return self.root / "state" / "scout-top100.json"

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


EXPIRY = datetime.timedelta(hours=48)
REASONS = {"r-have": "already have it", "r-goals": "not my goals",
           "r-heavy": "too heavy", "r-later": "not now"}
_TAP = re.compile(r"scout:([a-z-]+):(\d{1,20})")


def _parse_ts(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def _take_callbacks(paths: Paths) -> list:
    """Move the gateway's tap file aside, then read it. A tap the gateway appends after
    the move starts a fresh file and waits for the next run, so nothing is lost. A
    leftover .processing file from a crashed run is read first."""
    processing = paths.callbacks.with_name(paths.callbacks.name + ".processing")
    text = ""
    if processing.exists():
        text += processing.read_text(encoding="utf-8")
    if paths.callbacks.exists():
        incoming = paths.callbacks.with_name(paths.callbacks.name + ".incoming")
        os.replace(paths.callbacks, incoming)
        text += incoming.read_text(encoding="utf-8")
        with open(processing, "w", encoding="utf-8") as f:
            f.write(text)
        incoming.unlink()
    taps = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
            m = _TAP.fullmatch(d["data"])
            if m:
                taps.append((int(d["message_id"]), m.group(1), int(m.group(2))))
        except (ValueError, KeyError, TypeError):
            continue
    if processing.exists():
        processing.unlink()
    return taps


def apply_callbacks(paths: Paths, answers: dict, pending, now: datetime.datetime):
    """Apply Bill's taps in order, then expire a stale pending message to 'maybe'.

    The first yes/maybe/no on a find wins; a reason only attaches to a 'no'; a tap on a
    find that expired to 'maybe' replaces it once. Returns (answers, pending)."""
    finds = answers.setdefault("finds", {})
    for message_id, kind, repo_id in _take_callbacks(paths):
        key = str(repo_id)
        entry = finds.get(key)
        if kind in REASONS:
            if entry and entry.get("answer") == "no" and not entry.get("reason"):
                entry["reason"] = REASONS[kind]
            continue
        rung = 2 if kind.startswith("e-") else 1
        answer = kind[2:] if rung == 2 else kind
        expired = bool(entry and entry.get("expired") and entry.get("rung") == rung)
        if rung == 1:
            rewatch = bool(entry and entry.get("rewatch") and entry.get("answer") == "maybe")
            allowed = entry is None or expired or rewatch
        else:
            allowed = bool(entry) and (entry.get("rung") == 1 and entry.get("answer") == "yes"
                                       or expired)
        if allowed:
            name = (entry or {}).get("full_name") or (pending or {}).get("full_name", "")
            record_answer(answers, repo_id, name, rung, answer, None, now)
            finds[key].pop("expired", None)
            finds[key].pop("rewatch", None)
        if pending and pending.get("message_id") == message_id:
            pending = None
    if pending and now - _parse_ts(pending["sent_at"]) > EXPIRY:
        entry = finds.get(str(pending["repo_id"]))
        answered = bool(entry and entry.get("rung") == pending.get("rung", 1)
                        and entry.get("answer") and not entry.get("rewatch"))
        if not answered:  # never overwrite an answer Bill already gave
            record_answer(answers, pending["repo_id"], pending.get("full_name", ""),
                          pending.get("rung", 1), "maybe", None, now)
            finds[str(pending["repo_id"])]["expired"] = True
            finds[str(pending["repo_id"])].pop("rewatch", None)
        pending = None
    return answers, pending


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
