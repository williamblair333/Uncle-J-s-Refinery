# Draft — upstream issue for dwarvesf/claude-guardrails (NOT FILED)

Waiting on Bill's OK: filing is a public post. Checked 2026-10-22: no existing issue covers it
(open: #6, #14, #17).

---

**Title:** Permission-escalation hook never fires: grep reads the `--…` pattern as an option

**Body:**

`full/settings.json` (line 98 at `b3c3e15`) blocks permission escalation with:

```
grep -qEi "--dangerously-skip-permissions|--bypass-permissions"
```

Because the pattern starts with `--`, GNU grep parses it as an option, prints
`grep: unrecognized option '--dangerously-skip-permissions|--bypass-permissions'` to stderr and
exits 2. The `if` treats that as "no match", so the hook allows every command, including the
ones it exists to block. The error shows up in the hook's stderr on every Bash call.

Repro:

```
echo 'claude --bypass-permissions' | grep -qEi "--dangerously-skip-permissions|--bypass-permissions"; echo $?   # 2
echo 'claude --bypass-permissions' | grep -qEi -e "--dangerously-skip-permissions|--bypass-permissions"; echo $?  # 0
```

Fix: pass the pattern with `-e` (or put `--` before it). Happy to send a PR.
