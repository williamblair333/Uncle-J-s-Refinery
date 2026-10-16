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

# stack health: servers, indexes, crons, skills (quick; --full adds a ~30 s smoke test)
health *args:
    ./healthcheck.sh {{args}}

# find and fix drift (CLAUDE.md deploy, hooks, scopes); `just doctor --fix` applies
doctor *args:
    ./scripts/refinery-doctor.sh {{args}}

# re-index this repo for jcodemunch and jdocmunch
reindex:
    ./scripts/jcodemunch-reindex.sh && ./scripts/jdocmunch-reindex.sh

# rebuild docs/SKILLS.md and relink global skills into every agent's skill dir
skills:
    .venv/bin/python scripts/gen-skills-reference.py && ./scripts/skill-link.sh link

# search cross-project memory: just recall "what did we decide about X"
recall query:
    .venv-memweave/bin/python scripts/memweave/mw_search.py "{{query}}" --k 5

# Gemini judges Claude's work: just referee "what it must do" --diff main
referee task *args:
    .venv/bin/python scripts/referee.py --task "{{task}}" {{args}}

# one headless Antigravity (agy) prompt with honest exit codes
agy *args:
    .venv/bin/python scripts/ask_agy.py {{args}}
