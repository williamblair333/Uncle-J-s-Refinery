# Uncle J's Refinery — product brief

## Core job

An agent working in any repo on this machine gets structured retrieval — symbols,
sections, rows, prior decisions — instead of brute-force file reading, and the
person supervising it gets work that is checked before it is called done.

## Users

One developer (Bill) plus the agents running under their account, on Linux and
Git Bash on Windows. They already have git, Python 3.11+, Docker on Linux, and
the Claude Code CLI. They do not want to hand-register MCP servers, hand-run
index refreshes, or discover a broken retrieval path mid-task.

## Success

- Retrieval routes through the stack rather than `grep`: measured by
  `get_session_stats` token savings, not by intention.
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

Every command above appears in `README.md`; the gate fails on drift between the
two.

## Non-goals

- Hosting anything. This is a local-first toolkit, not a service.
- Replacing Claude Code's own memory. The local stores are canonical; native
  memory mirrors them.
- Multi-user support. One account, one machine, plus the Windows port.
- Cloud embedding providers on the default path. Offline ONNX stays the default.

## UI principles

- Terminal output is the interface. Default output is short; detail is opt-in.
- A failure names the thing that failed, the reason, and the next command to run.
- No raw tracebacks to the user; the traceback goes to a log and the message
  stays readable.
- Anything that blocks (pre-mortem, the first-run gate) names its override in
  the same message, so the way forward is never a guess.
- Silence means success. Scripts that succeed do not narrate.

## Verification scope — read this before trusting the block below

The `verify:` block covers the **product-quality subsystem** — the piece a
clean machine can exercise without the Claude Code CLI. It does **not** yet
prove the full `install.sh` path, because that registers MCP servers into a
Claude Code installation that does not exist inside a container, and pulls the
three jMunch packages plus the ONNX encoder from git.

That gap is a known limitation, not a pass. Closing it needs a stub Claude
config and a cached wheel set; until then, `healthcheck.sh` remains the only
evidence for the full stack, and it runs on the host rather than on a clean
machine.

The core task below is not a `--help` call: it validates a real brief end to end
— parsing, expectation adequacy, and README drift — and writes its verdict to a
file. That is the gate's own job minus the container step, which it cannot run
inside a container.

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
