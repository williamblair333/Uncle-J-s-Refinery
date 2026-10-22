#!/usr/bin/env python3
"""UserPromptSubmit hook: when Bill names a skill, make the model invoke it.

Skills are model-invoked, so a prompt that says "just-do-it all the things" can be
acted on without the skill ever loading. This hook reads the prompt, finds skill
names in it and tells the model to call the Skill tool for each one first.

A name counts when it appears as `/name`, or as a hyphenated name on its own
(`just-do-it`, `pre-mortem`). Single-word names (`judge`, `wizard`, `teach`) count
only in the `/name` form, since they are ordinary words in a sentence.

Never blocks and never fails loudly: any error means no output.
"""
import json
import os
import re
import sys

SKILL_DIRS = [os.path.expanduser("~/.claude/skills")]


def installed_skills(dirs=None):
    names = set()
    for d in dirs or SKILL_DIRS:
        try:
            for entry in os.listdir(d):
                if os.path.isfile(os.path.join(d, entry, "SKILL.md")):
                    names.add(entry)
        except OSError:
            continue
    return names


def named_skills(prompt, skills):
    found = []
    for name in sorted(skills, key=len, reverse=True):
        esc = re.escape(name)
        slash = re.search(rf"(?<![\w/.-])/{esc}(?![\w-])", prompt, re.I)
        bare = "-" in name and re.search(rf"(?<![\w/.-]){esc}(?![\w-])", prompt, re.I)
        if slash or bare:
            found.append(name)
    # Drop names that are only a substring of a longer match (e.g. grill-me inside grill-me-now).
    return sorted(set(found))


def main():
    try:
        data = json.load(sys.stdin)
        prompt = data.get("prompt") or ""
        names = named_skills(prompt, installed_skills())
    except Exception:
        return 0
    if not names:
        return 0
    listed = ", ".join(names)
    msg = (f"The user named skill(s): {listed}. Invoke each one with the Skill tool "
           "before any other action this turn, then follow it.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": msg}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
