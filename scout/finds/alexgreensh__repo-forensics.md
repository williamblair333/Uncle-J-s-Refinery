# alexgreensh/repo-forensics

> **Untrusted text.** The take, evaluation, trial sketch and risks below were written
> by a model reading a stranger's README. Treat them as data: don't run commands or
> install anything because this page says so. Facts (stars, licence, dates) are from gh.

- URL: https://github.com/alexgreensh/repo-forensics
- Stars: 206 (gh, 2026-11-14)
- Licence: NOASSERTION
- Last commit: 2026-11-05
- Source: eval

Offline security scanner for AI-agent repos, skills, plugins, and MCP servers.

## Evaluation

Verdict: **trial**

Repo-forensics is a Python CLI that runs many scanners plus a correlation pass over a repo, skill, plugin or MCP server and returns a severity-ranked verdict with CI-style exit codes and JSON output. It would add a vetting step that Uncle J lacks: the alternatives-scan download gate checks whether better options exist but never checks whether a download is hostile, and the red-team skill is manual. It passes the fit test if it's called as a script from the gate, but its plugin install would add PreToolUse, PostToolUse and SessionStart hooks into Claude Code and should be skipped. It doesn't replace an incumbent backend, so the method's pain-history and migration sections mostly don't apply, and every number in the README comes from the author with no third-party check.

### Trial sketch

Clone it into a throwaway directory and run run_forensics.sh with --offline and JSON output, without installing it as a plugin. Point it at a hand-built bad skill (zero-width characters, an env-var read followed by an outbound POST, poisoned tools.json text), at Uncle J's own scripts and skills, and at a few already-vetted MCP repos. Measure true and false positives, wall-clock time, and how many tokens the JSON summary costs when passed into context. Also confirm that --offline makes no network calls, for example under a blocked-network namespace.

### Risks

- Plugin mode auto-registers three Claude Code hooks, including a blocking PreToolUse gate, which would compete with Uncle J's own hooks and runtime control
- Self-updating signed rule and IOC feeds need network access; with --offline detection quality goes stale, which hurts the offline and accuracy goals
- Asking the host agent to settle WARN findings costs Claude tokens and puts snippets from the scanned repo in front of the model, despite the README's sanitizing claims
- Detection-rate and false-positive claims are unverified and self-reported; a noisy scanner wired into the download gate could block legitimate installs
