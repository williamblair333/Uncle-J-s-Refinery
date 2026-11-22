---
name: patch-upstream-hook-durably
description: Make a local fix to a hook or script owned by an upstream installer (e.g. claude-guardrails scan-commit.sh) survive reinstalls. Use an idempotent repo fix script with --check, wire it into the install script, and test against an upstream baseline.
---

# Patch an upstream-owned hook durably

## When to use
- A global hook installed from upstream (e.g. `~/.claude/hooks/scan-commit/scan-commit.sh` from dwarvesf/claude-guardrails) misbehaves, for example by flagging `sha256:<digest>` as a secret.
- The file is re-copied by an install script (e.g. `install-guardrails.sh`), so a hand edit would be silently dropped on the next reinstall.
- Earlier fixes of the same shape exist (`fix-guardrails-grep`, `fix-guardrails-defender`). Follow their pattern.

Don't use it for one-off edits to files the repo itself owns. Edit those directly.

## Steps

1. **Pre-mortem first.** The change touches hooks, the install script and main, so run the pre-mortem skill before you begin.
   - Expect UPGRADE DURABILITY to flag MEDIUM. Reinstall overwrites the patch, and the fix script is the mitigation.
   - Name the SECURITY tradeoff of any carve-out explicitly. For the digest fix, a 64-hex secret written as `sha256:<secret>` would pass. Keep the carve-out narrow so other patterns still fire.
   - List the exact files in the token scope: the fix script, the install script, the test, and the live hook path.

2. **Write the fix script** at `scripts/fix-guardrails-<name>.sh`:
   - **Idempotent.** Detect a marker comment and do nothing if the patch is already present.
   - **`--check` mode.** Report whether the patch is present and change nothing. This is the observability hook.
   - **Narrow edit.** Use `sed -E`, or whatever tools the hook already uses, so no new dependency is added. Mask only the specific case. For the digest fix, that's the hex-64 text after `sha256:`.
   - **Safe write.** Keep a `.bak`, write to a tmp file, then `mv` atomically. A failed sed must leave the original untouched.
   - **Marker comment.** Insert a comment in the patched hook that names the fix script, so a human reading the hook knows where the change came from.

3. **Wire it into the installer.** Call the fix script from `install-guardrails.sh` after the upstream copy, so every reinstall re-applies the patch.

4. **Write tests** in `tests/test_fix_guardrails_<name>.py` covering three cases:
   - **Baseline:** the unpatched upstream hook blocks the false-positive case. This proves the bug is real.
   - **After the fix:** the false-positive case passes.
   - **No regression:** the true-positive case is still blocked. For the digest fix, that's a bare 64-hex string.
   - Also check that `--check` reports correctly and that a second run is a no-op.

5. **Apply live, then ship.**
   - Run the fix script against the live hook on this host and confirm with `--check`.
   - Unblock any session that was waiting on the fix.
   - Go branch → PR → merge → back to main.

6. **Note the upstream report.** Record that the bug is worth reporting upstream, but don't file it unless asked.

## Recovery
- Restore the hook from `scan-commit.sh.bak`, or rerun `install-guardrails.sh`, which re-applies the fix.
