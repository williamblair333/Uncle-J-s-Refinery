#!/usr/bin/env bash
# `just gpu mtw2|shared|status` — who gets the RTX 3060.
#   shared: Ollama (Klarheit's pinned qwen3.5:9b) + Heretic at --fit-target 7300, 1 slot × 32k.
#   mtw2:   Ollama stopped, Klarheit timers disabled, Heretic at --fit-target 1024, 2 slots × 32k.
# Both on the GPU at once crash-looped Heretic on CUDA OOM (68 restarts, 2026-10-23), so one waits.
# Timers are disabled, not just stopped, so a reboot in mtw2 mode doesn't run trials against no Ollama.
# rv/m12 are `systemctl link`ed from their repos and `disable` deletes the link, so mtw2 mode saves
# each timer's file path and shared mode enables by path, which re-links it.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$PROJ_ROOT/state/gpu-mode"
SAVED="$PROJ_ROOT/state/gpu-mode.timers"
TIMERS=(klarheit-rv.timer klarheit-cycle.timer klarheit-m12.timer)

status() {
    echo "mode: $(cat "$STATE" 2>/dev/null || echo shared)"
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
    nvidia-smi --query-compute-apps=process_name,used_memory --format=csv,noheader
    echo "ollama: $(docker inspect -f '{{.State.Status}}' ollama 2>/dev/null || echo missing)"
    for t in "${TIMERS[@]}"; do echo "$t: $(systemctl --user is-enabled "$t" 2>/dev/null || true)"; done
    curl -s --max-time 5 localhost:8090/props |
        python3 -c 'import json,sys; d=json.load(sys.stdin); print("heretic: total_slots", d.get("total_slots"), "n_ctx", d.get("default_generation_settings", {}).get("n_ctx"))' \
        2>/dev/null || echo "heretic: not answering"
}

wait_heretic() {
    for _ in $(seq 1 60); do
        curl -sf --max-time 2 localhost:8090/health >/dev/null && return 0
        sleep 5
    done
    echo "heretic did not report healthy within 5 min: just heretic logs" >&2
    return 1
}

case "${1:-status}" in
    mtw2)
        mkdir -p "$(dirname "$STATE")"
        if [[ ! -s "$SAVED" ]]; then
            for t in "${TIMERS[@]}"; do
                # the link target, not the ~/.config symlink that `disable` deletes
                p="$(readlink -f "$(systemctl --user show -P FragmentPath "$t")")"
                if [[ -f "$p" ]]; then echo "$p" >> "$SAVED"; fi
            done
        fi
        systemctl --user disable --now "${TIMERS[@]}"
        docker stop ollama >/dev/null
        mkdir -p "$(dirname "$STATE")" && echo mtw2 > "$STATE"
        "$PROJ_ROOT/scripts/heretic.sh" up -d --force-recreate
        wait_heretic && status ;;
    shared)
        rm -f "$STATE"
        "$PROJ_ROOT/scripts/heretic.sh" up -d --force-recreate
        wait_heretic
        docker start ollama >/dev/null
        if [[ -s "$SAVED" ]]; then
            xargs systemctl --user enable --now < "$SAVED" && rm -f "$SAVED"
        else
            systemctl --user enable --now "${TIMERS[@]}"
        fi
        status ;;
    status) status ;;
    *) echo "usage: gpu-mode.sh mtw2|shared|status" >&2; exit 2 ;;
esac
