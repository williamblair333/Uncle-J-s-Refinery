# Uncle J's Refinery — product brief

## Core job

An agent can look up the piece it needs in any repo on this machine. It can find
a function or other named piece of code, a section in a document, a row in a
table, or a past decision without reading whole files. The person supervising
the agent gets work that is checked before anyone calls it done.

## Users

William and the agents that run under William's account use the toolkit on
Linux and in Git Bash on Windows. They already have git, Python 3.11+, Docker on
Linux, and the Claude Code CLI (its command-line interface). An MCP server gives
an assistant access to tools such as code search. Setup should register those
servers for William. The toolkit should keep its search indexes up to date and
catch broken lookups before they interrupt a task.

## Success

- Agents use the toolkit for lookups they would otherwise do with `grep`.
  Success is the token savings `get_session_stats` measures (tokens are chunks
  of text the model processes), not the intention to use the toolkit.
- `healthcheck.sh` reports all servers reachable and the index fresh.
- A new capability shipped here installs on a clean machine from the documented
  steps alone.
- **Time-to-first-result target: 900 seconds** — clone to a working install on a
  machine that has never seen this repo.

## First-run path

1. `git clone git@github.com:williamblair333/Uncle-J-s-Refinery.git`
2. `cd Uncle-J-s-Refinery`
3. `./install.sh`
4. `./healthcheck.sh`

Every command above also appears in `README.md`. The first-run gate fails if the two differ.

## Non-goals

- Hosting anything. The toolkit runs on your machine. It isn't a service.
- Replacing Claude Code's own memory. The local stores are the source of truth.
  Claude Code's memory mirrors them.
- Multi-user support. One account, one machine, plus the Windows port.
- Using a cloud provider by default to make embeddings, which are numeric
  representations that help find related text. The toolkit uses an offline ONNX
  model by default.

## UI principles

- The terminal is the interface. Show short messages by default and give users
  a way to ask for detail.
- Say what failed, why it failed, and which command to run next.
- Never show a raw traceback (the record of where an error occurred) to the
  user. Put it in the log and keep the terminal message readable.
- If a check stops the task, tell the user how to override it in the same
  message. This applies to the pre-mortem (a check for what could go wrong) and
  the first-run gate.
- When a script succeeds, it stays quiet.

## Verification scope — read this before trusting the block below

The `verify:` block checks the **product-quality subsystem**, which can run on a
clean machine without Claude Code. It leaves the full `install.sh` path
unverified. The installer needs Claude Code to register MCP servers. It also
pulls the three jMunch packages and the ONNX encoder from git.

Treat that gap as a known limitation of the block below, not a pass.

Since 2026-10-22, `just install-gate` has checked the full installer separately.
It runs `./install.sh --non-interactive --skip-optional` in a fresh
`debian:bookworm-slim` container. A stand-in for `claude` records each `mcp add`
command. The container uses prebuilt Python packages from the host's uv cache
(`scripts/clean-install-gate.sh`). This check needs Docker and network access
and takes minutes. The container run can't check that the servers connect or
that plugins install, because it has no real Claude Code. Run `healthcheck.sh`
on the host for that.

The check below isn't a quick `--help` call. It runs the gate's own job on a
real brief from start to finish: it reads the brief, checks whether its
expectations are sufficient, and looks for differences between the brief and the
README. It writes its verdict to a file. The only part it skips is the container
step, which can't run from inside a container.

```yaml
verify:
  image: debian:bookworm-slim
  network: required
  install:
    - apt-get update && apt-get install -y python3 python3-yaml
  run: python3 features/product-quality/first_run_gate.py --check features/product-quality/fixtures/good-project
  expect:
    - stdout_contains: "brief is runnable"
    - file: /tmp/first-run-gate-check.json
    - exit_code: 0
  time_target_seconds: 300
```
