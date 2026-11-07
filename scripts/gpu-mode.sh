#!/usr/bin/env bash
# `just gpu mtw2|shared|status` — who gets the RTX 3060.
#   shared: Ollama (Klarheit's pinned qwen3.5:9b) + Heretic at --fit-target 7300, 1 slot × 32k.
#   mtw2:   Ollama stopped, Klarheit timers disabled, Heretic at --fit-target 1024, 2 slots × 32k.
# Both on the GPU at once crash-looped Heretic on CUDA OOM (68 restarts, 2026-10-23), so one waits.
# Timers are disabled, not just stopped, so a reboot in mtw2 mode doesn't run trials against no Ollama.
# rv/m12 are `systemctl link`ed from their repos and `disable` deletes the link, so mtw2 mode saves
# each timer's file path and shared mode enables by path, which re-links it.
# Klarheit counts each slot missed in mtw2 mode as lost for good, so entering it takes an explicit
# flag and sends a Telegram, and leaving it reports how long the timers were off.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$PROJ_ROOT/state/gpu-mode"
SAVED="$PROJ_ROOT/state/gpu-mode.timers"
TIMERS=(klarheit-rv.timer klarheit-cycle.timer klarheit-m12.timer)
ACCEPT_FLAG=--accept-klarheit-loss

# A failed alert must not leave the GPU half-switched: say so and carry on.
alert() {
    (
        set -a
        # shellcheck disable=SC1091
        source "$PROJ_ROOT/.env"
        set +a
        # An explicit chain: set -e does nothing inside `( ... ) ||`.
        # shellcheck disable=SC1091
        [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] &&
            source "$PROJ_ROOT/lib/notify.sh" &&
            notify_send_text "$1"
    ) >/dev/null 2>&1 || echo "warning: Telegram alert not sent: $1" >&2
}

# Already in mtw2 mode means the timers are already off, so running it again costs nothing new.
refuse_without_accept() {
    [[ "$(cat "$STATE" 2>/dev/null)" == mtw2 ]] && return 0
    [[ "${1:-}" == "$ACCEPT_FLAG" ]] && return 0
    cat >&2 <<EOF
refused: this stops Klarheit's M11, M12 and cycle timers, and every slot missed while they're off
is lost for good. Nothing records a pause, so Klarheit reads the gap as misses.
To go ahead: just gpu mtw2 $ACCEPT_FLAG
Afterwards: just gpu shared
EOF
    exit 3
}

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
        refuse_without_accept "${2:-}"
        [[ "$(cat "$STATE" 2>/dev/null)" == mtw2 ]] ||
            alert "GPU mode mtw2 on dma64: Klarheit timers stopped, its slots are being lost until: just gpu shared"
        mkdir -p "$(dirname "$STATE")"
        if [[ ! -s "$SAVED" ]]; then
            for t in "${TIMERS[@]}"; do
                # the link target, not the ~/.config symlink that `disable` deletes;
                # an already-unlinked timer has no path, and readlink fails on that
                p="$(readlink -f "$(systemctl --user show -P FragmentPath "$t")" || true)"
                if [[ -f "$p" ]]; then echo "$p" >> "$SAVED"; fi
            done
        fi
        # Recorded first, so a failure below still shows as mtw2 and healthcheck warns.
        echo mtw2 > "$STATE"
        systemctl --user disable --now "${TIMERS[@]}"
        docker stop ollama >/dev/null
        "$PROJ_ROOT/scripts/heretic.sh" up -d --force-recreate
        wait_heretic && status ;;
    shared)
        off_minutes=""
        if [[ -f "$STATE" ]]; then off_minutes=$(( ($(date +%s) - $(stat -c %Y "$STATE")) / 60 )); fi
        rm -f "$STATE"
        # Klarheit needs Ollama, not Heretic: a broken Heretic must not keep its timers off.
        heretic_rc=0
        { "$PROJ_ROOT/scripts/heretic.sh" up -d --force-recreate && wait_heretic; } || heretic_rc=1
        docker start ollama >/dev/null
        if [[ -s "$SAVED" ]]; then
            xargs systemctl --user enable --now < "$SAVED" && rm -f "$SAVED"
        else
            systemctl --user enable --now "${TIMERS[@]}"
        fi
        if [[ -n "$off_minutes" ]]; then
            alert "GPU mode shared on dma64: Klarheit timers back after $off_minutes min off"
        fi
        status
        if (( heretic_rc != 0 )); then
            echo "Klarheit is back, but Heretic didn't come up: just heretic logs" >&2
            exit 1
        fi ;;
    status) status ;;
    *) echo "usage: gpu-mode.sh mtw2 $ACCEPT_FLAG|shared|status" >&2; exit 2 ;;
esac
