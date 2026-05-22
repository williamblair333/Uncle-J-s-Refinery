#!/usr/bin/env bash
# Checks installed vs HEAD for all MCP stack tools.
# Git is the golden reference — PyPI is not consulted for the four core packages.
# Exits 0 if everything is at HEAD, 1 if any git packages are behind.
#
# Usage:
#   ./scripts/check-stack-freshness.sh
#   GITHUB_TOKEN=ghp_... ./scripts/check-stack-freshness.sh   # 5000 req/hr vs 60

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCKFILE="$PROJ_ROOT/uv.lock"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

UPGRADES=0

_gh_curl() {
  local auth_args=()
  [[ -n "${GITHUB_TOKEN:-}" ]] && auth_args=(-H "Authorization: Bearer $GITHUB_TOKEN")
  curl -sf "${auth_args[@]}" -H "Accept: application/vnd.github.v3+json" "$@"
}

# Read the locked git commit SHA for a package from uv.lock.
# uv encodes the SHA as a URL fragment: git = "https://...repo.git#<sha>"
# Returns 7-char short SHA or "?" on failure.
parse_lock_sha() {
  local pkg=$1
  python3 - "$pkg" "$LOCKFILE" << 'PYEOF' 2>/dev/null || echo "?"
import sys, re
pkg, lockfile = sys.argv[1], sys.argv[2]
try:
    content = open(lockfile).read()
    # Match [[package]] block for exactly this package, then find git source URL
    pattern = (r'\[\[package\]\]\s+name\s*=\s*"' + re.escape(pkg) +
               r'".*?source\s*=\s*\{\s*git\s*=\s*"[^"]+#([a-f0-9]{40})"')
    m = re.search(pattern, content, re.DOTALL)
    print(m.group(1)[:7] if m else "?")
except Exception:
    print("?")
PYEOF
}

# GET /repos/{repo}/commits/HEAD → "sha7  YYYY-MM-DD"
gh_head() {
  _gh_curl "https://api.github.com/repos/$1/commits/HEAD" \
    | jq -r '"\(.sha[0:7])  \(.commit.committer.date[:10])"' 2>/dev/null || echo "?"
}

# How many commits is base_sha behind HEAD on the default branch?
gh_compare_ahead() {
  local repo=$1 base=$2
  _gh_curl "https://api.github.com/repos/$repo/compare/${base}...HEAD" \
    | jq -r '.ahead_by // "?"' 2>/dev/null || echo "?"
}

# Print the commit messages between base_sha and HEAD (up to 15).
show_commits_since() {
  local repo=$1 base=$2
  _GH_COMPARE=$(_gh_curl "https://api.github.com/repos/$repo/compare/${base}...HEAD" 2>/dev/null || true)
  export _GH_COMPARE
  python3 - << 'PYEOF' 2>/dev/null || true
import sys, json, os
try:
    data = json.loads(os.environ.get('_GH_COMPARE', '{}'))
    commits = data.get('commits', [])
    for c in commits[-15:]:
        sha  = c['sha'][:7]
        date = c['commit']['committer']['date'][:10]
        msg  = c['commit']['message'].split('\n')[0][:80]
        print(f"    {sha}  ({date})  {msg}")
    if len(commits) > 15:
        print(f"    {DIM}... {len(commits) - 15} more commits{NC}")
except Exception:
    pass
PYEOF
}

# Check a git-tracked package: compare locked SHA against GitHub HEAD.
check_git_pkg() {
  local label=$1 github=$2
  local installed_sha head_info head_sha head_date ahead

  installed_sha=$(parse_lock_sha "$label")
  head_info=$(gh_head "$github")
  head_sha=$(echo "$head_info" | awk '{print $1}')
  head_date=$(echo "$head_info" | awk '{print $2}')

  if [[ "$installed_sha" == "?" ]]; then
    printf "  ${YELLOW}?${NC}  %-22s could not read SHA from uv.lock\n" "$label"
    return
  fi
  if [[ "$head_sha" == "?" ]]; then
    printf "  ${YELLOW}?${NC}  %-22s installed=%-10s  GitHub HEAD fetch failed\n" "$label" "$installed_sha"
    return
  fi

  if [[ "$installed_sha" == "$head_sha" ]]; then
    printf "  ${GREEN}✓${NC}  %-22s %s  at HEAD (%s)\n" "$label" "$installed_sha" "$head_date"
  else
    ahead=$(gh_compare_ahead "$github" "$installed_sha")
    printf "  ${RED}↑${NC}  %-22s %s → %s  (%s commits behind HEAD)\n" \
      "$label" "$installed_sha" "$head_sha" "$ahead"
    UPGRADES=$((UPGRADES + 1))
    show_commits_since "$github" "$installed_sha"
    echo ""
  fi
}

# npm packages: just show latest (auto-fetched via npx on each run)
check_npm() {
  local label=$1 pkg=$2
  local latest
  latest=$(npm view "$pkg" version 2>/dev/null || echo "?")
  printf "  ${GREEN}·${NC}  %-22s latest=%-10s  auto via npx\n" "$label" "$latest"
}

# git-managed tools fetched via uvx: just show HEAD
check_uvx_git() {
  local label=$1 github=$2
  local head
  head=$(gh_head "$github")
  printf "  ${GREEN}·${NC}  %-22s HEAD=%s  auto via uvx\n" "$label" "$head"
}

# Read the pinned tag for a docker image from docker-compose.yml.
# Returns the tag portion after the last ':', or "" if no tag.
compose_tag() {
  local fragment=$1
  local compose="$SCRIPT_DIR/../claude-code-langfuse-template/docker-compose.yml"
  local line
  line=$(grep "image:.*${fragment}" "$compose" 2>/dev/null | head -1 | xargs)
  local img="${line#image: }"
  if [[ "$img" == *:* ]]; then
    echo "${img##*:}"
  else
    echo ""
  fi
}

# Latest release tag from GitHub (strips leading 'v').
gh_latest_release() {
  _gh_curl "https://api.github.com/repos/$1/releases/latest" \
    | jq -r '.tag_name // "?"' 2>/dev/null | sed 's/^v//' || echo "?"
}

# Check if the NEXT major version tag exists on Docker Hub (e.g. postgres:18 when pinned to :17).
# Returns "yes", "no", or "?".
dh_next_major_exists() {
  local image=$1 current_major=$2
  local next=$(( current_major + 1 ))
  local result
  result=$(curl -sf "https://hub.docker.com/v2/repositories/library/${image}/tags/${next}" 2>/dev/null)
  if [[ "$result" == *'"name"'* ]]; then
    echo "$next"
  else
    echo ""
  fi
}

# Check a Docker image pinned in docker-compose.yml.
# source: "github:owner/repo" | "dockerhub:image" | "chainguard"
# mode:   "actionable" (default) — counts behind as UPGRADE, shown in red
#         "infra"                 — informational only; only upgrade if Langfuse requires it
_check_docker_svc() {
  local label=$1 image_fragment=$2 source=$3 mode=${4:-actionable}
  local pinned

  pinned=$(compose_tag "$image_fragment")

  if [[ "$source" == "chainguard" ]]; then
    printf "  ${GREEN}·${NC}  %-22s auto-patched by Chainguard (floating latest)\n" "$label"
    return
  fi

  if [[ -z "$pinned" ]]; then
    printf "  ${YELLOW}~${NC}  %-22s no tag pinned\n" "$label"
    [[ "$mode" == "actionable" ]] && UPGRADES=$((UPGRADES + 1))
    return
  fi

  local pinned_major
  pinned_major=$(echo "$pinned" | cut -d. -f1)

  if [[ "$source" == dockerhub:* ]]; then
    local next_major
    next_major=$(dh_next_major_exists "${source#dockerhub:}" "$pinned_major")
    if [[ "$next_major" == "?" ]]; then
      printf "  ${YELLOW}?${NC}  %-22s :%-12s  fetch failed\n" "$label" "$pinned"
    elif [[ -n "$next_major" ]]; then
      if [[ "$mode" == "infra" ]]; then
        printf "  ${DIM}·${NC}  %-22s :%-12s  :${next_major} exists — update only if Langfuse requires it\n" "$label" "$pinned"
      else
        printf "  ${RED}↑${NC}  %-22s :%-12s  :${next_major} now available\n" "$label" "$pinned"
        UPGRADES=$((UPGRADES + 1))
      fi
    else
      printf "  ${GREEN}✓${NC}  %-22s :%-12s  no newer major\n" "$label" "$pinned"
    fi
  else
    local latest latest_major
    latest=$(gh_latest_release "${source#github:}")
    if [[ "$latest" == "?" ]]; then
      printf "  ${YELLOW}?${NC}  %-22s :%-12s  GitHub fetch failed\n" "$label" "$pinned"
      return
    fi
    latest_major=$(echo "$latest" | cut -d. -f1)
    if [[ "$pinned_major" == "$latest_major" ]]; then
      printf "  ${GREEN}✓${NC}  %-22s :%-12s  latest=%s (same major)\n" "$label" "$pinned" "$latest"
    elif [[ "$mode" == "infra" ]]; then
      printf "  ${DIM}·${NC}  %-22s :%-12s  latest=%s — update only if Langfuse requires it\n" "$label" "$pinned" "$latest"
    else
      printf "  ${RED}↑${NC}  %-22s :%-12s  latest=%s — new major available\n" "$label" "$pinned" "$latest"
      UPGRADES=$((UPGRADES + 1))
    fi
  fi
}

check_docker_svc()      { _check_docker_svc "$1" "$2" "$3" "actionable"; }
check_docker_infra()    { _check_docker_svc "$1" "$2" "$3" "infra"; }

echo ""
printf "${BOLD}Stack Freshness — $(date '+%Y-%m-%d %H:%M')${NC}\n"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "git  (locked SHA in uv.lock — git is the golden reference):"
check_git_pkg "jcodemunch-mcp" "jgravelle/jcodemunch-mcp"
check_git_pkg "jdatamunch-mcp" "jgravelle/jdatamunch-mcp"
check_git_pkg "jdocmunch-mcp"  "jgravelle/jdocmunch-mcp"
check_git_pkg "mempalace"      "MemPalace/mempalace"

echo ""
echo "npm  (fetched fresh via npx on each run):"
check_npm "context7" "@upstash/context7-mcp"

echo ""
echo "git  (fetched from HEAD via uvx on each run):"
check_uvx_git "serena" "oraios/serena"

echo ""
echo "docker  (Langfuse — update when new version available):"
check_docker_svc "langfuse"        "langfuse/langfuse:"     "github:langfuse/langfuse"
check_docker_svc "langfuse-worker" "langfuse-worker:"       "github:langfuse/langfuse"
echo ""
echo "docker  (Langfuse infrastructure — update only if Langfuse release notes require it):"
check_docker_infra "clickhouse"    "clickhouse-server"      "github:ClickHouse/ClickHouse"
check_docker_infra "redis"         "docker.io/redis:"       "github:redis/redis"
check_docker_infra "postgres"      "docker.io/postgres:"    "dockerhub:postgres"
check_docker_svc   "minio"         "chainguard/minio"       "chainguard"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ $UPGRADES -gt 0 ]]; then
  echo ""
  printf "${BOLD}To upgrade:${NC}\n"
  echo "  Python packages:"
  echo "    cd $PROJ_ROOT && uv lock --upgrade-package jcodemunch-mcp \\"
  echo "      --upgrade-package jdatamunch-mcp --upgrade-package jdocmunch-mcp \\"
  echo "      --upgrade-package mempalace && uv sync --inexact"
  echo "  Langfuse (safe to pull when new version available):"
  echo "    docker compose -f $PROJ_ROOT/claude-code-langfuse-template/docker-compose.yml pull langfuse langfuse-worker"
  echo "    docker compose -f $PROJ_ROOT/claude-code-langfuse-template/docker-compose.yml up -d"
  echo "  Infrastructure (postgres/redis/clickhouse) — only update if Langfuse release notes require it."
fi

echo ""
printf "${BOLD}GitHub Watches (→ Watch → Custom → Releases):${NC}\n"
echo "  https://github.com/jgravelle/jcodemunch-mcp"
echo "  https://github.com/jgravelle/jdatamunch-mcp"
echo "  https://github.com/jgravelle/jdocmunch-mcp"
echo "  https://github.com/MemPalace/mempalace"
echo "  https://github.com/oraios/serena"
echo "  https://github.com/upstash/context7"
echo "  https://github.com/langfuse/langfuse"
echo "  https://github.com/ClickHouse/ClickHouse"
echo "  https://github.com/minio/minio"
echo "  https://github.com/redis/redis"
echo "  https://github.com/docker-library/postgres"
echo ""
[[ -z "${GITHUB_TOKEN:-}" ]] && \
  printf "${YELLOW}Tip:${NC} export GITHUB_TOKEN=<pat> to raise GitHub API rate limit (60→5000 req/hr)\n"

exit $(( UPGRADES > 0 ? 1 : 0 ))
