#!/usr/bin/env bash
# RULE: the terse-reply skill must be invoked in every turn.
#
# Contract (shared by all force-rules.d/*.sh):
#   - $TURN_SLICE  : path to a file holding transcript lines since the last user prompt.
#   - $TRANSCRIPT  : path to the full transcript (JSONL) if a rule needs wider context.
#   - exit 0       : requirement satisfied — do not block.
#   - exit non-0   : requirement unmet — print ONE line to stdout; it becomes the
#                    block reason shown to the model.
#
# Compliance marker: a Skill tool-call serializes as ...,"name":"Skill","input":{"skill":"terse-reply"...
# The literal token "skill":"terse-reply" appears ONLY in a real invocation, never in
# the prose reminder ("invoke the terse-reply skill"), so this cannot false-match.
if grep -qF '"skill":"terse-reply"' "$TURN_SLICE"; then
  exit 0
fi
echo 'Invoke the terse-reply skill on your draft before ending the turn (non-optional).'
exit 1
