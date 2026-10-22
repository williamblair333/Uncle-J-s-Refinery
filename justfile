# Uncle J's Refinery — run `just` for this list.
# Each recipe is one line; the logic lives in the scripts it calls.

# list recipes
default:
    @just --list

# install or repair the stack (idempotent)
setup *args:
    ./install.sh {{args}}

# run the tests (only tests/: bare pytest also collects third-party clones in reviewed/)
test *args:
    .venv/bin/python -m pytest -q tests {{args}}

# invisible-Unicode sweep of tracked files + vendored-engine drift check (read-only)
audit:
    ./scripts/jscrub/audit-repo.sh

# stack health: servers, indexes, crons, skills (quick; --full adds a ~30 s smoke test)
health *args:
    ./healthcheck.sh {{args}}

# what's waiting in every /opt/proj HANDOFF, plus unpushed/uncommitted repos
waiting *args:
    python3 scripts/waiting_sweep.py {{args}}

# real ./install.sh in a fresh container, claude shimmed (~10 min; --worktree for uncommitted)
install-gate *args:
    ./scripts/clean-install-gate.sh {{args}}

# find and fix drift (CLAUDE.md deploy, hooks, scopes); `just doctor --fix` applies
doctor *args:
    ./scripts/refinery-doctor.sh {{args}}

# re-index this repo for jcodemunch and jdocmunch
reindex:
    ./scripts/jcodemunch-reindex.sh && ./scripts/jdocmunch-reindex.sh

# rebuild docs/SKILLS.md and relink global skills into every agent's skill dir
skills:
    .venv/bin/python scripts/gen-skills-reference.py && ./scripts/skill-link.sh link

# skill library on disk, loaded by nothing: just skill-lib sync | list [filter] | add <skill>
skill-lib *args:
    python3 scripts/skill_library.py {{args}}

# search cross-project memory: just recall "what did we decide about X"
recall query:
    .venv-memweave/bin/python scripts/memweave/mw_search.py "{{query}}" --k 5

# Gemini judges Claude's work: just referee "what it must do" --diff main
referee task *args:
    .venv/bin/python scripts/referee.py --task "{{task}}" {{args}}

# one headless Antigravity (agy) prompt with honest exit codes
agy *args:
    .venv/bin/python scripts/ask_agy.py {{args}}

# repo scout: build the capability map once (review scout/map.md after)
scout-seed *args:
    python3 scripts/scout/run.py seed {{args}}

# repo scout: one nightly run by hand (--dry-run prints instead of sending)
scout *args:
    python3 scripts/scout/run.py run {{args}}

# repo scout: map review state, queue, pending message, answers so far
scout-status:
    python3 scripts/scout/run.py status

# live build view for any project: just preview publish|watch|status|list (runs in your cwd)
[positional-arguments]
preview *args:
    cd "{{invocation_directory()}}" && "{{justfile_directory()}}/.venv/bin/python" "{{justfile_directory()}}/scripts/live_preview/cli.py" "$@"

# chat page for the local model (+ Claude/agy offload) at http://127.0.0.1:8091
chat *args:
    .venv/bin/python scripts/local_chat/server.py {{args}}

# start whichever backend config/ask_local.env names (heretic, or Ollama + its model)
ask-local-up:
    ./scripts/ask-local-up.sh

# ask_local's abliterated model (llama-server, 127.0.0.1:8090): just heretic up -d | down | logs (up via dcup)
heretic *args:
    ./scripts/heretic.sh {{args}}
