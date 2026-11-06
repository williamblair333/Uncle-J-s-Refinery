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

# offload report: work sent to agy/Heretic/local vs Claude (default 7 days)
offload *args:
    .venv/bin/python scripts/offload_report.py {{args}}

# workaround detector bench: fire rate on real transcripts (default last 7 days)
workaround-bench *args:
    python3 scripts/workaround_scan.py --replay {{args}}

# ask-gate bench: permission questions at turn end on real transcripts, and what Bill replied (default 30 days)
ask-gate-bench *args:
    python3 scripts/ask_gate.py --replay {{args}}

# chance-check bench: labelled cases by default; --replay N checks N random real turn ends and prints every flag
chance-bench *args:
    python3 scripts/chance_check.py {{ if args == "" { "--bench" } else { args } }}

# events this project's tests depend on, and how each gets forced: just forcing-list [--list] [--file F] (runs in your cwd)
forcing-list *args:
    cd "{{invocation_directory()}}" && python3 "{{justfile_directory()}}/scripts/forcing_list.py" {{args}}

# hook bench: replay real transcripts through every behaviour-changing hook — fire rate, errors, false hits
hook-bench *args:
    python3 scripts/hook_bench.py {{args}}

# hook bench export: bundle transcripts and settings for replay without ~/.claude
hook-bench-export dir="state/hook-bench-export":
    python3 scripts/hook_bench.py --export {{dir}}

# skill router bench: replay Bill's real prompts, fire rate and sample hits per routed skill
router-bench *args:
    python3 scripts/router_bench.py {{args}}

# self-check bench: how often "check yourself" turns up a real correction (all transcripts)
check-bench *args:
    python3 scripts/check_bench.py {{args}}

# Bill's meta-questions ("why didn't you…") per session per week, with the Monday trend line
meta-questions *args:
    python3 scripts/meta_questions.py {{args}}

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

# Claude Code session with a quiet headless Firefox browser MCP (this session only)
browser *args:
    claude {{args}} --mcp-config "$(./scripts/firefox-mcp.sh --config)"

# web pages → markdown files for local retrieval: just web2md URL --out DIR [--sitemap|--crawl] [--max N]
web2md *args:
    uv run -q --script scripts/web2md.py {{args}}

# start whichever backend config/ask_local.env names (heretic, or Ollama + its model)
ask-local-up:
    ./scripts/ask-local-up.sh

# ask_local's abliterated model (llama-server, 127.0.0.1:8090): just heretic up -d | down | logs (up via dcup)
heretic *args:
    ./scripts/heretic.sh {{args}}

# who gets the GPU: just gpu mtw2 (Heretic takes it; Ollama + Klarheit paused) | shared | status
gpu *args:
    ./scripts/gpu-mode.sh {{args}}

# image/video generation (ComfyUI, 127.0.0.1:8188): just comfy up -d | down | logs | build (up via dcup)
comfy *args:
    ./scripts/comfy.sh {{args}}

# download + sha256-check ComfyUI's models into /opt/models (optional filter: z-image, wan2.2)
comfy-models *args:
    ./scripts/comfy-models.sh {{args}}

# one Z-Image-Turbo image (1024²) → /opt/outputs/comfyui: just image "prompt" [--seed N]
image prompt *args:
    python3 scripts/comfy_job.py image "{{prompt}}" {{args}}

# one Wan 2.2 clip (832×480, 81 frames) → /opt/outputs/comfyui: just video "prompt" [--frames N]
video prompt *args:
    python3 scripts/comfy_job.py video "{{prompt}}" {{args}}

# speech-to-text (whisper.cpp, CPU, 127.0.0.1:8092): just whisper up -d | down | logs (up via dcup)
whisper *args:
    ./scripts/speech.sh whisper {{args}}

# cloned-voice text-to-speech (Chatterbox Nano, CPU, 127.0.0.1:8093): just tts up -d | down | logs
tts *args:
    ./scripts/speech.sh tts {{args}}

# small CPU model for the Pi / tc-vmh-03 (llama-server, 127.0.0.1:8096): SMALL_MODEL=qwen3.5-4b-heretic SMALL_GGUF=… just small up -d
small *args:
    ./scripts/small.sh {{args}}
