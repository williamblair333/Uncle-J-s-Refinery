"""Citation audit: scan a Claude Code session transcript for URLs the assistant
emitted, cross-check each against WebFetch / `gh` evidence in the SAME transcript,
and append verified/unverified records to state/citation-audit.jsonl.

Deterministic — NO LLM. Structurally closes the fabrication path: a URL the
assistant stated but never fetched/verified is flagged 'unverified'.

Invoked by scripts/citation-audit.sh (Stop hook). Reads transcript path from the
hook stdin JSON ('transcript_path'). STDLIB ONLY.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "state/citation-audit.jsonl"
# URLs as the assistant would write them; trailing punctuation trimmed.
_URL_RE = re.compile(r"https?://[^\s\)\]\}>\"'`]+")
_TRAILING = ".,;:!?"


def _clean(url):
    return url.rstrip(_TRAILING)


def extract_urls_from_record(rec):
    urls = set()
    if rec.get("type") != "assistant":
        return urls
    for block in (rec.get("message", {}).get("content") or []):
        if isinstance(block, dict) and block.get("type") == "text":
            for m in _URL_RE.findall(block.get("text", "")):
                urls.add(_clean(m))
    return urls


def collect_fetched_evidence(records):
    """URLs fetched via WebFetch + raw `gh` command strings run via Bash."""
    urls, gh_cmds = set(), []
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        for block in (rec.get("message", {}).get("content") or []):
            if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                continue
            name = block.get("name")
            inp = block.get("input") or {}
            if name == "WebFetch" and inp.get("url"):
                urls.add(_clean(inp["url"]))
            elif name == "Bash":
                cmd = inp.get("command", "")
                if re.search(r"\bgh\b", cmd):
                    gh_cmds.append(cmd)
    return {"urls": urls, "gh_cmds": gh_cmds}


def classify_url(url, fetched):
    if url in fetched["urls"]:
        return "verified"
    # gh path-match: a github URL's path appearing in a gh command counts.
    path = re.sub(r"^https?://(www\.)?github\.com/", "", url)
    if path and path != url:
        for cmd in fetched["gh_cmds"]:
            if path in cmd:
                return "verified"
    return "unverified"


def _read_records(transcript_path):
    records = []
    for line in Path(transcript_path).read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def audit_transcript(transcript_path):
    records = _read_records(transcript_path)
    fetched = collect_fetched_evidence(records)
    stated = set()
    for rec in records:
        stated |= extract_urls_from_record(rec)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = Path(transcript_path).stem
    out = []
    for url in sorted(stated):
        out.append({"ts": ts, "session": session, "url": url,
                    "status": classify_url(url, fetched)})
    return out


def main():
    # Hook stdin: {"transcript_path": "...", ...}. Tolerate missing/empty.
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    tp = payload.get("transcript_path")
    if not tp or not Path(tp).exists():
        return
    records = audit_transcript(tp)
    if not records:
        return
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
