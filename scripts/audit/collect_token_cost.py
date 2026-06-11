# scripts/audit/collect_token_cost.py
"""Collector A: always-on token cost per component.

Sources measured (all static, all estimates at ~4 bytes/token):
  1. Global + project CLAUDE.md, split by ## heading, mapped to components.
  2. Hook strings in ~/.claude/settings.json and .claude/settings.json
     (the standing-instruction/echo payloads injected each session).
  3. Skill descriptions (name + description frontmatter of every SKILL.md
     reachable from ~/.claude/skills and global-skills/) — injected as the
     available-skills list each session.
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
