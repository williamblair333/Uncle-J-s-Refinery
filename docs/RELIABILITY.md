# Reliability layer reference

The core stack (jMunch trio + MemPalace + Serena + Context7 + DuckDB)
gives Claude the *right tools*. The reliability layer makes sure
Claude *actually uses them correctly*. Four components:

| Component                     | What it does                                                      | When to turn off            |
| ----------------------------- | ----------------------------------------------------------------- | --------------------------- |
| prior-art-check skill         | MemPalace lookup BEFORE the first real tool call every session    | never; it's just a lookup   |
| judge skill                   | Spawn code-reviewer subagent BEFORE Edit/Write lands              | for throwaway prototyping   |
| Ralph harness                 | while-true loop that only stops when risk is low + PRD is DONE    | only in live runs           |
| dwarvesf claude-guardrails    | Block pasted secrets, scan tool output for prompt-injection       | never (low cost, high value)|
| Superpowers plugin            | 20+ skills: brainstorm, systematic-debug, TDD, verify-before-done | if total skill count > 25   |
| Ralph Wiggum plugin           | /ralph slash command (Anthropic official version)                 | --                          |

## How the pieces compose

```
user message
   │
   ▼
UserPromptSubmit hook (dwarvesf)       <- blocks pasted credentials
   │
   ▼
prior-art-check skill                  <- "have we solved this?"
   │   MemPalace hit? use it as context
   ▼
main work                              <- jcodemunch / serena / etc.
   │
   ▼
Edit or Write about to fire
   │
   ▼
judge skill                            <- spawn code-reviewer subagent
   │   verdict: approve / concerns / block
   ▼
tool executes                          <- or blocks here
   │
   ▼
PostToolUse hook (dwarvesf)            <- scan tool output for injection
   │
   ▼
response to user
```

All five gates can fire in under 15 seconds for a typical coding turn.
Ralph runs this whole pipeline on every iteration.

## What each component buys you

### prior-art-check

Answers the question "does the agent ask itself 'have we solved this
before' before working?" with **yes, now it does**. Without this skill,
MemPalace is a tool the agent *could* call but usually won't. With it,
the agent checks prior work on every non-trivial prompt. Zero cost on
cold palaces; 1-2 second overhead on warm ones.

### judge

Catches the four classic hallucination patterns on code changes:

1. Invented functions (call `foo.bar()` where `bar` doesn't exist)
2. Invented imports (import a module that isn't a dep)
3. Wrong signature (skip required parameter)
4. Missed callers (rename symbol, forget to update all sites)

Evidence fed to the subagent comes from `get_blast_radius`,
`find_references`, `get_untested_symbols`, `get_pr_risk_profile`. The
judge is not a separate LLM watching for hallucinations at the token
level (that's what HaluGate does, and it only works with vLLM-hosted
open models). This is the production-ready equivalent for Claude.

### Ralph harness (our version vs. the plugin)

Anthropic's Ralph plugin (`/ralph`) is the standard Huntley pattern:
loop the agent on a prompt file until it says done.

Our harness (`ralph-harness.sh`) adds structural done-gates:

- `get_changed_symbols` — confirms something actually moved
- `get_untested_symbols(changed_only=true)` — blocks if new code has
  no tests
- `get_pr_risk_profile` — blocks if composite risk exceeds threshold

So the loop only exits when BOTH the model says "done" AND the stack's
structural view agrees. Solves the classic Ralph failure mode where
the model confidently declares victory on a broken change.

Pick the plugin for exploratory runs; pick the harness for anything
you plan to commit.

### Superpowers

The single biggest agent-reliability upgrade available in 2026.
20+ skills enforcing real-engineering discipline:

- `brainstorming` — forces requirements clarification before code
- `systematic-debugging` — 4-phase root-cause process, no speculative
  fixes until evidence is gathered
- `test-driven-development` — RED-GREEN-REFACTOR on new code
- `verification-before-completion` — agent must prove the fix works
  before claiming success
- `requesting-code-review` — well-composed hand-off to reviewer
  subagents (pairs with our judge skill)

Caveat from the Claude Code community: total active skill count matters
for context budget. Best practice is 20-25 active skills max; more than
that causes skill-selection bias. Superpowers adds 20+ on its own, so
after installing it, remove skills you don't actually use.

### dwarvesf/claude-guardrails

Security layer, hooks-based:

- **UserPromptSubmit secret scanner** — before your prompt reaches the
  model, scans it for live AWS keys, GitHub/Anthropic/OpenAI tokens,
  PEM blocks, BIP39 phrases. Blocks and warns. Prevents both model
  exposure and session-log leakage.
- **PostToolUse injection scanner** — scans Read / WebFetch / Bash
  output for known prompt-injection patterns. Warns (doesn't block)
  so legitimate security content still works.

Based on Trail of Bits + Lasso research + Anthropic's official security
docs. Low overhead. Worth keeping on always.

## Tier 2 — mentioned, not installed

If you want more later, these are the next things worth adding:

- **Langfuse** (https://langfuse.com) — agent observability. Native
  Claude Agent SDK integration. Every tool call and completion becomes
  an OpenTelemetry span. Self-hostable via Docker. 19k stars, MIT
  license. Best for "why did my agent do X two sessions ago."
- **Anthropic-Cybersecurity-Skills** (mukul975) — 754 skills mapped to
  MITRE ATT&CK / NIST CSF. Overkill unless you work in security.
- **Verdent Review Subagent** — commercial. Cross-validates a change
  with Claude + Gemini + GPT-5.2 concurrently. Expensive per review;
  use on high-stakes PRs only.

## Disable / uninstall

```powershell
# Remove our skills
Remove-Item -Recurse -Force $env:USERPROFILE\.claude\skills\prior-art-check
Remove-Item -Recurse -Force $env:USERPROFILE\.claude\skills\judge

# Remove dwarvesf guardrails (hooks get merged into settings.json; you
# need to edit that manually if you want to revert)
Remove-Item -Recurse -Force $env:USERPROFILE\Downloads\claude\_stack_setup\claude-guardrails

# Remove Superpowers / Ralph
# Inside claude: /plugin uninstall superpowers
# Inside claude: /plugin uninstall ralph-wiggum
```
