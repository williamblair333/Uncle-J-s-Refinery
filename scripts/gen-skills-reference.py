#!/usr/bin/env python3
"""Build docs/SKILLS.md: every skill and workflow in this repo, how it fires, and whether it
works outside Claude Code.

Usage:
  gen-skills-reference.py            # (re)write docs/SKILLS.md (repo content only)
  gen-skills-reference.py --check    # exit 1 if docs/SKILLS.md is stale; never writes
  gen-skills-reference.py --host     # print the full view for this machine: repo skills plus
                                     # installed plugins and skills that exist only in
                                     # ~/.claude/skills (flagged NOT BACKED UP); never writes

The committed file covers only the repo (global-skills/, features/*/skills/,
global-workflows/), so it is identical on every host and --check is a plain text comparison.
Requires pyyaml (use the stack venv); there is no fallback parser, because a degraded parse
would render different text and make --check flap.
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

PURPOSE_MAX = 160
PURPOSE_MIN = 25

# Portability heuristic, checked in order. A hit means the skill calls something that
# only exists in this stack or in Claude Code; other agents can still read the steps.
STACK_RE = re.compile(r"mcp__|jcodemunch|jdocmunch|jdatamunch|memweave|\bserena\b|ask_local|mw_search")
CLAUDE_RE = re.compile(
    r"AskUserQuestion|TodoWrite|\bSkill tool\b|\bAgent tool\b|~/\.claude|\.claude/|"
    r"\bclaude (?:--|plugin|agents|mcp)|settings\.json|PreToolUse|SessionStart|superpowers:"
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_frontmatter(text: str) -> dict:
    text = text.lstrip("\n")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def purpose(description: str) -> str:
    desc = " ".join(str(description or "").split())
    sentences = re.findall(r".+?[.!?](?=\s|$)|.+$", desc)
    text = ""
    for s in sentences:  # first sentence, extended while it is too short to say anything
        text = f"{text} {s.strip()}".strip()
        if len(text) >= PURPOSE_MIN:
            break
    if len(text) > PURPOSE_MAX:
        text = text[: PURPOSE_MAX - 1].rstrip() + "…"
    return text.replace("|", "\\|")


def portability(skill_dir: Path) -> str:
    text = "\n".join(read(p) for p in sorted(skill_dir.rglob("*.md")))
    if STACK_RE.search(text):
        return "Refinery stack"
    if CLAUDE_RE.search(text):
        return "Claude Code"
    return "any agent"


def read_skill(skill_md: Path, name: str = None, origin: str = "") -> dict:
    fm = parse_frontmatter(read(skill_md))
    user_only = str(fm.get("disable-model-invocation", "")).lower() == "true"
    return {
        "name": name or str(fm.get("name") or skill_md.parent.name),
        "purpose": purpose(fm.get("description", "")),
        "fires": "you" if user_only else "auto",
        "portable": portability(skill_md.parent),
        "origin": origin,
    }


def upstream_origin(skill_dir: Path) -> str:
    up = skill_dir / "UPSTREAM"
    if up.is_file():
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)", read(up))
        if m:
            return f"vendored: {m.group(1)}"
    return "repo"


def collect(repo: Path, home: Path, host: bool = False) -> dict:
    sections = {"repo": [], "plugins": [], "local": [], "workflows": []}
    repo_names = set()

    for skill_md in sorted((repo / "global-skills").glob("*/SKILL.md")):
        sections["repo"].append(read_skill(skill_md, origin=upstream_origin(skill_md.parent)))
        repo_names.add(skill_md.parent.name)
    for skill_md in sorted((repo / "features").glob("*/skills/*/SKILL.md")):
        feature = skill_md.parent.parent.parent.name
        sections["repo"].append(read_skill(skill_md, origin=f"feature: {feature}"))
        repo_names.add(skill_md.parent.name)

    for js in sorted((repo / "global-workflows").glob("*.js")):
        doc = js.with_suffix(".md")
        fm = parse_frontmatter(read(doc)) if doc.is_file() else {}
        sections["workflows"].append({
            "name": js.stem, "purpose": purpose(fm.get("description", "")),
            "fires": "you", "portable": "Claude Code", "origin": "repo"})

    if not host:
        return sections

    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    if registry.is_file():
        plugins = json.loads(read(registry)).get("plugins", {})
        for key in sorted(plugins):
            installs = plugins[key] or []
            if not installs:
                continue
            install = Path(installs[0].get("installPath", ""))
            plugin = key.split("@")[0]
            version = installs[0].get("version", "?")
            for skill_md in sorted(install.glob("skills/*/SKILL.md")):
                sections["plugins"].append(read_skill(
                    skill_md, name=f"{plugin}:{skill_md.parent.name}",
                    origin=f"plugin {plugin} {version}"))

    claude_skills = home / ".claude" / "skills"
    repo_root = str(repo.resolve())
    for entry in sorted(claude_skills.iterdir()) if claude_skills.is_dir() else []:
        if entry.is_symlink() and str(entry.resolve()).startswith(repo_root):
            continue
        if entry.name in repo_names:
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            sections["local"].append(read_skill(skill_md, origin="NOT BACKED UP: ~/.claude/skills only"))
    return sections


HEADER = """# Skills reference

<!-- Generated by scripts/gen-skills-reference.py. Do not edit by hand: re-run the script. -->

Every skill and workflow kept in this repo, with what it does and how portable it is. Skills
are plain `SKILL.md` folders (the agentskills.io format), so any agent that reads that format
can use them; `scripts/skill-link.sh` links `global-skills/` into both `~/.claude/skills`
(Claude Code) and `~/.agents/skills` (Codex, Gemini CLI, Copilot CLI).

Third-party plugin skills (superpowers and others) and skills that exist only on one machine
are not listed here, because they differ per host. See them with
`.venv/bin/python scripts/gen-skills-reference.py --host`.

**Fires** — `auto`: the agent can pick it up on its own from the description; `you`: only
runs when you type `/name`.
**Works in** — `any agent`: plain instructions; `Claude Code`: calls Claude Code tools
(AskUserQuestion, hooks, ~/.claude paths), so another agent can follow it with those steps
adapted; `Refinery stack`: also needs this stack's MCP servers. Heuristic, from the text.
"""

HOST_NOTE = "\n> Host view of this machine (from `--host`): includes plugins and local-only skills. Not committed.\n"

SECTION_TITLES = {
    "repo": ("In this repo (backed up)", "`global-skills/` and `features/*/skills/`. Git-tracked, mirrored to GitHub."),
    "plugins": ("Plugins (third-party)", "Installed with `/plugin install`; reinstall from their upstream repos. Not copied here."),
    "local": ("Local only — not backed up", "Present in `~/.claude/skills` with no repo copy. Move into `global-skills/` to keep them."),
    "workflows": ("Workflows", "`global-workflows/*.js`, run with the Workflow tool (Claude Code only)."),
}


def render(sections: dict, host: bool = False) -> str:
    out = [HEADER + (HOST_NOTE if host else "")]
    shown = [k for k in SECTION_TITLES if host or k in ("repo", "workflows")]
    out.append("Totals: " + ", ".join(f"{len(sections[k])} {k}" for k in shown) + ".\n")
    for key in shown:
        rows = sections[key]
        if not rows:
            continue
        title, blurb = SECTION_TITLES[key]
        out.append(f"\n## {title}\n\n{blurb}\n")
        out.append("| Skill | What it does | Fires | Works in | Source |")
        out.append("|---|---|---|---|---|")
        for r in rows:
            out.append(f"| `{r['name']}` | {r['purpose']} | {r['fires']} | {r['portable']} | {r['origin']} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    repo_default = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=repo_default)
    ap.add_argument("--home", type=Path, default=Path.home())
    ap.add_argument("--output", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 if the output file is stale; never write")
    mode.add_argument("--host", action="store_true", help="print this machine's full view; never write")
    args = ap.parse_args(argv)
    if yaml is None:
        print("pyyaml is required: run with the stack venv (.venv/bin/python)", file=sys.stderr)
        return 2
    if args.host:
        sys.stdout.write(render(collect(args.repo, args.home, host=True), host=True))
        return 0
    output = args.output or args.repo / "docs" / "SKILLS.md"
    text = render(collect(args.repo, args.home))
    if args.check:
        current = read(output) if output.is_file() else ""
        if current != text:
            print(f"{output} is stale: run scripts/gen-skills-reference.py", file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
