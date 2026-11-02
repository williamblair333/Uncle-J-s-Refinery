#!/usr/bin/env python3
"""PreToolUse hook: the skills skill_router.py named for this prompt run before other work.

Naming a skill isn't running it. 2026-11-02: Bill had to ask twice before a plan review used its
review skills. The router records the skills it named in ~/.claude/state/skill-router/<session>.json.
This hook removes each one as the Skill tool invokes it. The first other tool call while any are
left is denied once, with the list. The retry goes through, so a skill the model declines (one line
saying why) never deadlocks a session.

FAIL OPEN: bad input, unreadable state, or an unwritable deny marker -> allow. Subagents (agent_id
in the input) pass. SKILL_GATE_OFF=1 turns it off. Denies go to denies.jsonl in the state dir.
"""
import json
import os
import re
import sys
import time


def state_file(session: str):
    session = re.sub(r"[^\w.-]", "", os.path.basename(session or ""))
    if not session:
        return None
    root = os.environ.get("SKILL_ROUTER_STATE") or os.path.expanduser("~/.claude/state/skill-router")
    return os.path.join(root, session + ".json")


def write(path: str, data: dict) -> bool:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def main() -> int:
    try:
        return gate()
    except Exception:          # any surprise in the input or state: allow, silently
        return 0


def gate() -> int:
    if os.environ.get("SKILL_GATE_OFF"):
        return 0
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            return 0
        if event.get("agent_id"):
            return 0
        path = state_file(event.get("session_id") or "")
        if not path or not os.path.isfile(path):
            return 0
        with open(path) as fh:
            state = json.load(fh)
        left = [s for s in state.get("skills", []) if isinstance(s, str)]
    except Exception:
        return 0

    tool = event.get("tool_name") or ""
    if tool == "Skill":
        ti = event.get("tool_input")
        name = str(ti.get("skill") or "") if isinstance(ti, dict) else ""
        if name in left:
            left.remove(name)
            if left:
                write(path, {**state, "skills": left})
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return 0
    if not left or state.get("denied"):
        return 0
    # Mark before denying: if the mark can't be written, a deny could repeat forever. Allow instead.
    if not write(path, {**state, "denied": True}):
        return 0
    try:
        with open(os.path.join(os.path.dirname(path), "denies.jsonl"), "a") as fh:
            fh.write(json.dumps({"ts": int(time.time()), "tool": tool, "left": left}) + "\n")
    except OSError:
        pass
    reason = ("The skill router named skills for this prompt that haven't run: "
              + ", ".join(left) + ". Invoke each with the Skill tool now, or say in one line why "
              "it doesn't fit. Then retry this call (one-time per prompt; a retry goes through).")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
