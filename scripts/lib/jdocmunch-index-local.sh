# shellcheck shell=bash
# run_index_local ROOT NAME — one repo's jdocmunch index refresh, through the CLI.
#
# Sourced by scripts/jdocmunch-reindex.sh, and by tests/test_jdocmunch_index_local.py
# with a stub CLI. The caller defines: JDOCMUNCH (the jdocmunch-mcp binary), PY (a
# python for the JSON verdict), LOG, log(), is_local_only(), canonical_root() and
# the LOCAL_ONLY_IGNORE map.
#
# WHY THE CLI AND NOT THE PYTHON API (switched 2026-10-23)
#
# The Python API call existed because the CLI had no way to pass ignore patterns.
# Upstream #108 added --extra-ignore-pattern, --no-ai-summaries and --embeddings, so
# the CLI now carries every posture this script sets. Keeping two routes meant two
# places that had to agree on the privacy posture; now there is one.
#
# THE CLI EXITS 0 ON FAILURE. Verified 2026-10-23 on jdocmunch-mcp 1.149.0: a missing
# folder prints {"success": false, "error": "Folder not found: ..."} and exits 0.
# The old fallback trusted the exit code, so a failed refresh counted as reindexed.
# The verdict is read from the JSON instead; no parseable verdict is a failure.
#
# HISTORY — the prune-compensation shim is GONE (2026-08-16). Upstream #102 fixed the
# `str.lstrip("./")` dot-dir prune bug it worked around. Repro, if it needs re-checking:
#
#     mkdir -p r/keepdir r/.worktrees/slug-a && git -C r init -q
#     printf '.worktrees/\n' > r/.gitignore
#     printf '# Kept\n\nalpha\n' > r/keepdir/kept.md
#     printf '# Copy\n\nbeta\n'  > r/.worktrees/slug-a/copy.md
#     # jdocmunch-mcp index-local --path r -> file_count 1 when fixed, 2 when broken
#
# WHAT IS LOAD-BEARING: the --extra-ignore-pattern loop. Those patterns keep
# credential-bearing files out of both the corpus and the cached raw mirror under
# ~/.doc-index. Do not remove them along with anything else.
run_index_local() {
    local root=$1 name=$2
    local local_only=0 extra_ignore="" pattern out rc

    # See LOCAL_ONLY_ROOTS in jdocmunch-reindex.sh for why these are forced off
    # rather than left to index-local's defaults, and why the test keys on the
    # source root rather than the repo name.
    if is_local_only "$root"; then
        local_only=1
        extra_ignore="${LOCAL_ONLY_IGNORE[$(canonical_root "$root")]:-}"
    fi

    local -a cli_args=(index-local --path "$root" --name "$name")
    # State the privacy posture on every run. "reindexed=1" alone cannot tell you
    # whether a corpus was summarized by a remote provider; this line can.
    if [[ "$local_only" -eq 1 ]]; then
        cli_args+=(--no-ai-summaries --embeddings off)
        while IFS= read -r pattern; do
            [[ -n "$pattern" ]] && cli_args+=(--extra-ignore-pattern "$pattern")
        done <<<"$extra_ignore"
        printf 'mode: local-only (no summarizer, no embeddings) — %s\n' "$name" >>"$LOG"
        [[ -n "$extra_ignore" ]] && printf 'forced exclusions: %s\n' \
            "$(printf '%s' "$extra_ignore" | paste -sd'|' -)" >>"$LOG"
    else
        printf 'mode: default (summaries/embeddings per environment) — %s\n' "$name" >>"$LOG"
    fi

    # Stream to the log as it runs (tee), and keep a copy to read the verdict from.
    out="$(mktemp "${TMPDIR:-/tmp}/jdoc-index-local.XXXXXX")" || return 1
    "$JDOCMUNCH" "${cli_args[@]}" 2>>"$LOG" | tee -a "$LOG" >"$out"
    rc=${PIPESTATUS[0]}
    if [[ "$rc" -eq 0 ]]; then
        # jdoc#65: providers can chatter on stdout, so take the last JSON object
        # that carries a "success" key rather than parsing the whole stream.
        "$PY" -c '
import json, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
dec, verdict, i = json.JSONDecoder(), None, text.find("{")
while i != -1:
    try:
        obj, end = dec.raw_decode(text, i)
    except ValueError:
        i = text.find("{", i + 1)
        continue
    if isinstance(obj, dict) and "success" in obj:
        verdict = obj
    i = text.find("{", end)
sys.exit(0 if verdict and verdict.get("success") is True else 1)
' "$out"
        rc=$?
        [[ "$rc" -ne 0 ]] && log "ERROR   $name — index-local reported no success (CLI exit 0)"
    fi
    rm -f -- "$out"
    return "$rc"
}
