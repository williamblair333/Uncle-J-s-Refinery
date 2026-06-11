# Pay-for-itself Audit (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First run of the mission's standing test — deterministic collectors measure each stack component's always-on token cost, maintenance burden, and benefit signals, joined into `state/payoff-scorecard.md`.

**Architecture:** A component manifest (`scripts/audit/components.json`) is the single source of truth for what a "component" is and how to match it (CLAUDE.md headings, file globs, commit keywords). Three stdlib-only Python collectors emit JSON to `state/payoff-audit/`; a synthesizer joins them into a markdown scorecard. No LLM calls anywhere in the pipeline — the judgment pass happens later, in-session, reading the scorecard. Missing data is reported explicitly (`"missing"` list), never guessed.

**Tech Stack:** Python 3.11 stdlib only (json, re, subprocess, fnmatch, pathlib, datetime), bash runner, pytest (existing CI harness, 0 API calls).

**Principles (from spec):** deterministic-first (P1); every collector must run offline; token figures are estimates (bytes/4) and labeled as such.

---

### Task 1: Component manifest + shared lib

**Files:**
- Create: `scripts/audit/components.json`
- Create: `scripts/audit/audit_lib.py`
- Test: `tests/test_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit.py
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "audit"))
import audit_lib

REPO = Path(__file__).parent.parent

def test_manifest_loads_and_has_required_fields():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    assert len(comps) >= 8
    for c in comps:
        assert c["id"], "every component needs an id"
        assert isinstance(c.get("commit_keywords", []), list)
        assert isinstance(c.get("file_patterns", []), list)

def test_est_tokens():
    assert audit_lib.est_tokens(b"") == 0
    assert audit_lib.est_tokens(b"abcd" * 100) == 100  # 400 bytes -> 100 tokens

def test_match_component_by_keyword_and_file():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    hit = audit_lib.match_components(comps, subject="fix: hnsw corruption repair",
                                     files=["scripts/mempalace-repair-now.sh"])
    assert "mempalace" in hit
    miss = audit_lib.match_components(comps, subject="docs: typo", files=["README.md"])
    assert miss == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /opt/proj/Uncle-J-s-Refinery && .venv/bin/python -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audit_lib'`

- [ ] **Step 3: Write the manifest**

```json
{
  "_comment": "Single source of truth for the pay-for-itself audit. Patterns are fnmatch globs relative to repo root; keywords are case-insensitive substrings matched against commit subjects.",
  "components": [
    {"id": "mempalace",
     "claude_md_headings": ["Memory — mempalace"],
     "file_patterns": ["scripts/mempalace-*", "features/mempalace/*", "scripts/turbovecdb-*"],
     "commit_keywords": ["mempalace", "hnsw", "fts5", "chromadb", "palace", "pickle", "turbovecdb"]},
    {"id": "jmunch-retrieval",
     "claude_md_headings": ["Code work", "Data work", "Docs work", "Tools by modality"],
     "file_patterns": ["scripts/jcodemunch-*", "uv.lock", "pyproject.toml"],
     "commit_keywords": ["jcodemunch", "jdatamunch", "jdocmunch", "serena", "reindex", "post-upgrade"]},
    {"id": "dreaming",
     "claude_md_headings": [],
     "file_patterns": ["features/dreaming/*"],
     "commit_keywords": ["dream", "playbook", "langfuse trace"]},
    {"id": "telegram",
     "claude_md_headings": [],
     "file_patterns": ["features/telegram*", "config/telegram-agents.toml"],
     "commit_keywords": ["telegram", "gateway", "notify"]},
    {"id": "guardrails-discipline",
     "claude_md_headings": [],
     "file_patterns": ["hooks/*", "global-skills/pre-mortem/*", "global-skills/smart-review/*"],
     "commit_keywords": ["guard", "pre-mortem", "premortem", "smart-review", "bypass", "hook"]},
    {"id": "routing-policy",
     "claude_md_headings": ["Retrieval Stack Routing Policy", "Output Token Economy", "Docker Port Registry"],
     "file_patterns": ["CLAUDE.md"],
     "commit_keywords": ["claude.md", "routing"]},
    {"id": "reliability",
     "claude_md_headings": [],
     "file_patterns": ["healthcheck.sh", "scripts/session-start-autofix.sh", "scripts/auto-maintain.sh", "scripts/session-end-check.sh", "install*.sh", "lib/*"],
     "commit_keywords": ["healthcheck", "autofix", "auto-maintain", "cron", "install", "session-end"]},
    {"id": "skills-ecosystem",
     "claude_md_headings": [],
     "file_patterns": ["global-skills/*", "tests/test_skills.py"],
     "commit_keywords": ["skill", "frontmatter"]},
    {"id": "ralph",
     "claude_md_headings": [],
     "file_patterns": ["*ralph*"],
     "commit_keywords": ["ralph"]},
    {"id": "langfuse-observability",
     "claude_md_headings": [],
     "file_patterns": ["features/langfuse/*", "docker-compose*"],
     "commit_keywords": ["langfuse", "observability", "trace"]}
  ]
}
```

- [ ] **Step 4: Write the lib**

```python
# scripts/audit/audit_lib.py
"""Shared helpers for the pay-for-itself audit collectors. Stdlib only."""
import fnmatch
import json
from pathlib import Path


def load_components(manifest_path):
    data = json.loads(Path(manifest_path).read_text())
    return data["components"]


def est_tokens(blob: bytes) -> int:
    # Documented estimate: ~4 bytes/token for English/markdown.
    return len(blob) // 4


def match_components(components, subject="", files=()):
    """Return the set of component ids matching a commit subject and file list."""
    subject_l = subject.lower()
    hits = set()
    for c in components:
        if any(k in subject_l for k in c.get("commit_keywords", [])):
            hits.add(c["id"])
            continue
        for f in files:
            if any(fnmatch.fnmatch(f, pat) for pat in c.get("file_patterns", [])):
                hits.add(c["id"])
                break
    return hits


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Strip empty collections explicitly (CLAUDE.md MCP response rule).
    clean = {k: v for k, v in payload.items() if v is not None and v != [] and v != {}}
    path.write_text(json.dumps(clean, indent=1, ensure_ascii=False))
    return path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/audit/components.json scripts/audit/audit_lib.py tests/test_audit.py
git commit -m "feat(audit): component manifest + shared lib for pay-for-itself audit"
```

---

### Task 2: Collector A — always-on token cost

**Files:**
- Create: `scripts/audit/collect_token_cost.py`
- Test: `tests/test_audit.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_audit.py
import collect_token_cost

def test_split_md_sections():
    md = "# Title\nintro\n## Alpha\naaaa\n## Beta\nbbbb\nbbbb\n"
    sections = collect_token_cost.split_sections(md)
    names = [s[0] for s in sections]
    assert names == ["(preamble)", "Alpha", "Beta"]
    assert sections[2][1].count("bbbb") == 2

def test_map_sections_to_components():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    out = collect_token_cost.map_sections(comps,
        [("Retrieval Stack Routing Policy", "x" * 400), ("Unknown Heading", "y" * 400)])
    assert out["routing-policy"]["est_tokens"] == 100
    assert out["_unmapped"]["est_tokens"] == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'collect_token_cost'`

- [ ] **Step 3: Write the collector**

```python
# scripts/audit/collect_token_cost.py
"""Collector A: always-on token cost per component.

Sources measured (all static, all estimates at ~4 bytes/token):
  1. Global + project CLAUDE.md, split by ## heading, mapped to components.
  2. Hook strings in ~/.claude/settings.json and .claude/settings.json
     (the standing-instruction/echo payloads injected each session).
  3. Skill descriptions (name + description frontmatter of every SKILL.md
     reachable from ~/.claude/skills) — injected as the available-skills list.
Anything unmappable lands in _unmapped, never silently dropped.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_lib

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]


def split_sections(md_text):
    """Return [(heading, body), ...] for ## headings; text before the first ## is (preamble)."""
    parts = re.split(r"^## +(.+)$", md_text, flags=re.M)
    sections = [("(preamble)", parts[0])]
    for i in range(1, len(parts), 2):
        sections.append((parts[i].strip(), parts[i + 1]))
    return sections


def map_sections(components, sections):
    out = {}
    for heading, body in sections:
        tok = audit_lib.est_tokens(body.encode())
        target = "_unmapped"
        for c in components:
            if any(h.lower() in heading.lower() for h in c.get("claude_md_headings", [])):
                target = c["id"]
                break
        slot = out.setdefault(target, {"est_tokens": 0, "sections": []})
        slot["est_tokens"] += tok
        slot["sections"].append(heading)
    return out


def hook_payload_tokens(settings_path):
    """Sum the sizes of hook command strings — proxy for per-session injected text."""
    if not settings_path.exists():
        return 0
    try:
        data = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    total = 0
    for hook_list in (data.get("hooks") or {}).values():
        total += audit_lib.est_tokens(json.dumps(hook_list).encode())
    return total


def skill_descriptions_tokens(skills_dirs):
    total, count = 0, 0
    for d in skills_dirs:
        for sk in Path(d).expanduser().glob("**/SKILL.md"):
            try:
                head = sk.read_text(errors="replace")[:2000]
            except OSError:
                continue
            m = re.search(r"^description:\s*(.+)$", head, flags=re.M)
            if m:
                total += audit_lib.est_tokens((sk.parent.name + m.group(1)).encode())
                count += 1
    return total, count


def main():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    missing = []

    result = {"_estimate_basis": "bytes/4", "components": {}}
    for label, p in [("global", HOME / ".claude/CLAUDE.md"), ("project", REPO / "CLAUDE.md")]:
        if not p.exists():
            missing.append(str(p))
            continue
        mapped = map_sections(comps, split_sections(p.read_text()))
        for cid, info in mapped.items():
            slot = result["components"].setdefault(cid, {"est_tokens": 0, "sources": []})
            slot["est_tokens"] += info["est_tokens"]
            slot["sources"].append(f"CLAUDE.md[{label}]: {len(info['sections'])} sections")

    hooks_tok = (hook_payload_tokens(HOME / ".claude/settings.json")
                 + hook_payload_tokens(REPO / ".claude/settings.json"))
    result["components"].setdefault("guardrails-discipline", {"est_tokens": 0, "sources": []})
    result["components"]["guardrails-discipline"]["est_tokens"] += hooks_tok
    result["components"]["guardrails-discipline"]["sources"].append("settings.json hook strings")

    sk_tok, sk_count = skill_descriptions_tokens([HOME / ".claude/skills", REPO / "global-skills"])
    result["components"].setdefault("skills-ecosystem", {"est_tokens": 0, "sources": []})
    result["components"]["skills-ecosystem"]["est_tokens"] += sk_tok
    result["components"]["skills-ecosystem"]["sources"].append(f"{sk_count} SKILL.md descriptions")

    result["missing"] = missing
    out = audit_lib.write_json(REPO / "state/payoff-audit/token-cost.json", result)
    print(f"token-cost: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v`
Expected: 5 passed

- [ ] **Step 5: Run the collector against the real repo and eyeball output**

Run: `.venv/bin/python scripts/audit/collect_token_cost.py && head -40 state/payoff-audit/token-cost.json`
Expected: JSON with routing-policy as the largest CLAUDE.md consumer (~8k tokens across both files); `_unmapped` present; no traceback.

- [ ] **Step 6: Commit**

```bash
git add scripts/audit/collect_token_cost.py tests/test_audit.py
git commit -m "feat(audit): collector A — always-on token cost per component"
```

---

### Task 3: Collector B — maintenance burden from git history

**Files:**
- Create: `scripts/audit/collect_maintenance.py`
- Test: `tests/test_audit.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_audit.py
import collect_maintenance

SAMPLE_LOG = """abc1|2026-06-10|fix: hnsw corruption repair in nightly cron
scripts/mempalace-repair-now.sh

def2|2026-06-09|feat: telegram inline button
features/telegram-gateway/bot.py

ghi3|2026-06-08|docs: session-end notes
HANDOFF.md
"""

def test_parse_git_log():
    commits = collect_maintenance.parse_log(SAMPLE_LOG)
    assert len(commits) == 3
    assert commits[0] == ("abc1", "2026-06-10",
                          "fix: hnsw corruption repair in nightly cron",
                          ["scripts/mempalace-repair-now.sh"])

def test_classify_maintenance():
    assert collect_maintenance.is_maintenance("fix: hnsw corruption repair") is True
    assert collect_maintenance.is_maintenance("feat: telegram inline button") is False
    assert collect_maintenance.is_maintenance("repair cron dedup") is True

def test_aggregate_by_component():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    agg = collect_maintenance.aggregate(comps, collect_maintenance.parse_log(SAMPLE_LOG))
    assert agg["mempalace"]["commits"] == 1
    assert agg["mempalace"]["maintenance_commits"] == 1
    assert agg["telegram"]["maintenance_commits"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'collect_maintenance'`

- [ ] **Step 3: Write the collector**

```python
# scripts/audit/collect_maintenance.py
"""Collector B: maintenance burden per component from git history (90 days).

A commit is 'maintenance' when its subject says fix/repair/corrupt/hotfix/revert —
i.e., the stack maintaining itself rather than gaining capability. Commit→component
mapping reuses the manifest keywords + file globs. Commits matching no component
are counted under _unmatched so coverage gaps are visible.
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_lib

REPO = Path(__file__).resolve().parents[2]
MAINT_RE = re.compile(r"^(fix|hotfix|revert)\b|repair|corrupt", re.I)


def parse_log(text):
    """Parse `git log --pretty=%h|%ad|%s --date=short --name-only` output."""
    commits, current = [], None
    for line in text.splitlines():
        if "|" in line and re.match(r"^[0-9a-f]{4,40}\|", line):
            if current:
                commits.append(current)
            h, d, s = line.split("|", 2)
            current = (h, d, s, [])
        elif line.strip() and current:
            current[3].append(line.strip())
    if current:
        commits.append(current)
    return commits


def is_maintenance(subject):
    return bool(MAINT_RE.search(subject))


def aggregate(components, commits):
    agg = {c["id"]: {"commits": 0, "maintenance_commits": 0} for c in components}
    agg["_unmatched"] = {"commits": 0, "maintenance_commits": 0}
    for _, _, subject, files in commits:
        targets = audit_lib.match_components(components, subject, files) or {"_unmatched"}
        for t in targets:
            agg[t]["commits"] += 1
            agg[t]["maintenance_commits"] += int(is_maintenance(subject))
    for v in agg.values():
        v["maintenance_share"] = round(v["maintenance_commits"] / v["commits"], 2) if v["commits"] else 0.0
    return agg


def main():
    comps = audit_lib.load_components(REPO / "scripts/audit/components.json")
    log = subprocess.run(
        ["git", "-C", str(REPO), "log", "--since=90.days",
         "--pretty=%h|%ad|%s", "--date=short", "--name-only"],
        capture_output=True, text=True, check=True).stdout
    commits = parse_log(log)
    result = {"window_days": 90, "total_commits": len(commits),
              "components": aggregate(comps, commits)}
    out = audit_lib.write_json(REPO / "state/payoff-audit/maintenance.json", result)
    print(f"maintenance: {out} ({len(commits)} commits)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, then run against the real repo**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v && .venv/bin/python scripts/audit/collect_maintenance.py && head -30 state/payoff-audit/maintenance.json`
Expected: 8 passed; mempalace maintenance_share visibly the highest of all components; `_unmatched` nonzero but a minority.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit/collect_maintenance.py tests/test_audit.py
git commit -m "feat(audit): collector B — maintenance burden from 90-day git history"
```

---

### Task 4: Collector C — benefit counters

**Files:**
- Create: `scripts/audit/collect_benefits.py`
- Test: `tests/test_audit.py` (append)

**Note for executor:** before Step 3, inspect the real formats with
`head -5 state/hook-blocks.log` and `ls ~/.code-index/`. The parser below counts
lines per matched guard name and tolerates unknown lines; if the real format
differs materially, adjust `GUARD_RE` only — keep the tolerant-count fallback.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_audit.py
import collect_benefits

SAMPLE_BLOCKS = """2026-06-10T10:00:00 grep-guard BLOCKED grep -r foo
2026-06-10T11:00:00 edit-surface-guard BLOCKED settings.json
2026-06-11T05:00:00 grep-guard BLOCKED grep -rn bar
garbage line without a guard
"""

def test_count_hook_blocks():
    counts = collect_benefits.count_blocks(SAMPLE_BLOCKS)
    assert counts["grep-guard"] == 2
    assert counts["edit-surface-guard"] == 1
    assert counts["_unparsed"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'collect_benefits'`

- [ ] **Step 3: Write the collector**

```python
# scripts/audit/collect_benefits.py
"""Collector C: benefit signals per component. Every source that can't be read
is listed in `missing` — explicit gaps, no guesses.

Sources:
  1. state/hook-blocks.log         -> guard catches (guardrails-discipline)
  2. ~/.code-index/** session/stats files -> jcodemunch tokens_saved if persisted
  3. MemPalace SQLite              -> drawer count, wings (read-only, stdlib sqlite3)
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit_lib

HOME = Path.home()
REPO = Path(__file__).resolve().parents[2]
GUARD_RE = re.compile(r"([a-z0-9_-]*guard[a-z0-9_-]*)", re.I)


def count_blocks(text):
    counts = {}
    for line in filter(str.strip, text.splitlines()):
        m = GUARD_RE.search(line)
        key = m.group(1).lower() if m else "_unparsed"
        counts[key] = counts.get(key, 0) + 1
    return counts


def jcodemunch_saved_tokens():
    """Best-effort scan of ~/.code-index for a persisted tokens_saved figure."""
    best = None
    for p in (HOME / ".code-index").glob("**/*.json"):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"(?:total_)?tokens_saved"\s*:\s*(\d+)', text):
            val = int(m.group(1))
            best = max(best or 0, val)
    return best


def mempalace_counts(db_path):
    if not db_path.exists():
        return None
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        try:
            n = conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]
        except sqlite3.Error:
            return None
    return {"embeddings_rows": n}


def main():
    missing, result = [], {"components": {}}

    blocks_path = REPO / "state/hook-blocks.log"
    if blocks_path.exists():
        result["components"]["guardrails-discipline"] = {
            "hook_blocks": count_blocks(blocks_path.read_text(errors="replace"))}
    else:
        missing.append(str(blocks_path))

    saved = jcodemunch_saved_tokens()
    if saved is not None:
        result["components"]["jmunch-retrieval"] = {"tokens_saved_best": saved}
    else:
        missing.append("~/.code-index tokens_saved")

    # Adjust at execution time if the palace lives elsewhere (check features/mempalace/install.sh).
    db = HOME / ".mempalace/chroma/chroma.sqlite3"
    mp = mempalace_counts(db)
    if mp:
        result["components"]["mempalace"] = mp
    else:
        missing.append(str(db))

    result["missing"] = missing
    out = audit_lib.write_json(REPO / "state/payoff-audit/benefits.json", result)
    print(f"benefits: {out} (missing: {len(missing)})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests, then run against the real machine**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v && .venv/bin/python scripts/audit/collect_benefits.py && cat state/payoff-audit/benefits.json`
Expected: 9 passed; hook_blocks counts present; if `missing` lists the MemPalace DB path, find the real path (`grep -o '/[^" ]*chroma.sqlite3' features/mempalace/install.sh` or `scripts/mempalace-repair-now.sh`) and fix the `db =` line, then rerun.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit/collect_benefits.py tests/test_audit.py
git commit -m "feat(audit): collector C — benefit counters (guards, retrieval savings, palace size)"
```

---

### Task 5: Scorecard synthesizer + runner

**Files:**
- Create: `scripts/audit/build_scorecard.py`
- Create: `scripts/audit/run-audit.sh`
- Test: `tests/test_audit.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_audit.py
import build_scorecard

def test_scorecard_renders_all_components_and_flags_gaps():
    token = {"components": {"mempalace": {"est_tokens": 100, "sources": ["x"]}}}
    maint = {"components": {"mempalace": {"commits": 10, "maintenance_commits": 9,
                                          "maintenance_share": 0.9}}}
    bene = {"components": {}, "missing": ["benefits source"]}
    md = build_scorecard.render(token, maint, bene)
    assert "| mempalace |" in md
    assert "0.9" in md
    assert "benefits source" in md          # missing data surfaced, not hidden
    assert "Verdict" in md                  # column exists, left blank for judgment pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_scorecard'`

- [ ] **Step 3: Write synthesizer + runner**

```python
# scripts/audit/build_scorecard.py
"""Joins the three collector JSONs into state/payoff-scorecard.md.
Pure assembly — verdicts are intentionally blank; the judgment pass
(human + LLM, in-session) fills them in against the README Mission."""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "state/payoff-audit"


def render(token, maint, bene):
    ids = sorted(set(token.get("components", {})) | set(maint.get("components", {}))
                 | set(bene.get("components", {})))
    lines = [
        f"# Pay-for-itself scorecard — {date.today().isoformat()}",
        "",
        "Mission test: every component must pay for itself against "
        "Right > Cheap-in-total > Inventive > Local — or be removed.",
        "Token figures are estimates (bytes/4). Verdicts are filled by the judgment pass.",
        "",
        "| Component | Always-on est. tokens/session | Commits (90d) | Maint. share | Benefit signals | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for cid in ids:
        t = token.get("components", {}).get(cid, {})
        m = maint.get("components", {}).get(cid, {})
        b = bene.get("components", {}).get(cid, {})
        bsig = "; ".join(f"{k}={v}" for k, v in b.items()) or "—"
        lines.append(f"| {cid} | {t.get('est_tokens', '—')} | {m.get('commits', '—')} | "
                     f"{m.get('maintenance_share', '—')} | {bsig} | |")
    gaps = (token.get("missing") or []) + (bene.get("missing") or [])
    if gaps:
        lines += ["", "## Missing data (collect before judging affected rows)", ""]
        lines += [f"- {g}" for g in gaps]
    return "\n".join(lines) + "\n"


def main():
    inputs = {}
    for name in ("token-cost", "maintenance", "benefits"):
        p = AUDIT / f"{name}.json"
        inputs[name] = json.loads(p.read_text()) if p.exists() else {"components": {}, "missing": [f"{p} not generated"]}
    md = render(inputs["token-cost"], inputs["maintenance"], inputs["benefits"])
    out = REPO / "state/payoff-scorecard.md"
    out.write_text(md)
    print(f"scorecard: {out}")


if __name__ == "__main__":
    main()
```

```bash
# scripts/audit/run-audit.sh
#!/usr/bin/env bash
# Pay-for-itself audit — runs all collectors then builds the scorecard.
# Deterministic; no LLM calls; safe to re-run anytime.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=.venv/bin/python
for c in collect_token_cost collect_maintenance collect_benefits build_scorecard; do
  "$PY" "scripts/audit/${c}.py"
done
echo "Done. Review state/payoff-scorecard.md, then run the judgment pass in-session."
```

- [ ] **Step 4: Run tests, make runner executable, run end-to-end**

Run: `chmod +x scripts/audit/run-audit.sh && .venv/bin/python -m pytest tests/test_audit.py -v && bash scripts/audit/run-audit.sh && cat state/payoff-scorecard.md`
Expected: 10 passed; scorecard renders with ~10 component rows, mempalace showing the highest maintenance share; Missing-data section honest about gaps.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit/build_scorecard.py scripts/audit/run-audit.sh tests/test_audit.py
git commit -m "feat(audit): scorecard synthesizer + run-audit.sh runner"
```

---

### Task 6: Wire into CI + docs

**Files:**
- Modify: `.github/workflows/ci.yml` (append a job following the existing `test-session-end-check` job's pattern)
- Modify: `CHANGELOG.md` (prepend entry)

- [ ] **Step 1: Add CI job** — copy the structure of the existing `test-session-end-check` job in `.github/workflows/ci.yml`, renamed `test-audit`, with the run step:

```yaml
  test-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install pytest
      - run: python -m pytest tests/test_audit.py -v
```

(Match the existing jobs' checkout/python action versions exactly — read the file first and reuse whatever versions the other jobs pin.)

- [ ] **Step 2: Verify tests pass with system python the way CI runs them**

Run: `python3 -m pytest tests/test_audit.py -v`
Expected: 10 passed (collectors import stdlib only, so no venv needed for tests)

- [ ] **Step 3: CHANGELOG entry**

Prepend under the top `---`:

```markdown
## 2026-06-11 — feat: pay-for-itself audit (Improvement Program Phase 1)

### Added
- **`scripts/audit/`**: component manifest + three deterministic collectors
  (token cost, 90-day maintenance burden, benefit counters) + scorecard
  synthesizer + `run-audit.sh`. Output: `state/payoff-scorecard.md`. No LLM
  calls in the pipeline; missing data reported explicitly.
- **`tests/test_audit.py`** + `test-audit` CI job (10 tests, 0 API calls).
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml CHANGELOG.md
git commit -m "feat(audit): CI job + changelog for pay-for-itself audit"
```

---

### Task 7: First real run + judgment pass (in-session, not a script)

- [ ] **Step 1:** `bash scripts/audit/run-audit.sh`
- [ ] **Step 2:** Resolve every entry in the scorecard's Missing-data section (fix paths in collectors, rerun) until the list is empty or each gap has a written reason.
- [ ] **Step 3:** Judgment pass — in-session, fill the Verdict column (keep / fix / delete) per component, citing the numbers and the README Mission. This is the single permitted LLM step of Phase 1.
- [ ] **Step 4:** Present verdicts to Bill for sign-off (deletions are never automatic — spec risk note).
- [ ] **Step 5:** Move agreed deletions/fixes into ROADMAP Phase 4; commit scorecard summary (scorecard itself lives in `state/`, gitignored — commit the ROADMAP changes only).
