#!/usr/bin/env bash
# Checks installed vs latest versions of all MCP stack tools.
# When behind, fetches and displays release notes so you can judge relevance.
# Exits 0 if everything is current, 1 if any PyPI upgrades are available.
#
# Usage:
#   ./scripts/check-stack-freshness.sh
#   GITHUB_TOKEN=ghp_... ./scripts/check-stack-freshness.sh   # 5000 req/hr vs 60

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$PROJ_ROOT/.venv/bin/python3"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

UPGRADES=0

_gh_curl() {
  local auth_args=()
  [[ -n "${GITHUB_TOKEN:-}" ]] && auth_args=(-H "Authorization: Bearer $GITHUB_TOKEN")
  curl -sf "${auth_args[@]}" -H "Accept: application/vnd.github.v3+json" "$@"
}

venv_version() {
  "$VENV_PY" -c "import importlib.metadata; print(importlib.metadata.version('$1'))" 2>/dev/null || echo ""
}

pypi_latest() {
  curl -sf "https://pypi.org/pypi/$1/json" | jq -r '.info.version' 2>/dev/null || echo "?"
}

npm_latest() {
  npm view "$1" version 2>/dev/null || echo "?"
}

gh_head() {
  _gh_curl "https://api.github.com/repos/$1/commits/HEAD" \
    | jq -r '"\(.sha[0:7])  \(.commit.committer.date[:10])"' 2>/dev/null || echo "?"
}

# Fetch release notes for all versions newer than $installed and print them.
show_changelog() {
  local github=$1 installed=$2
  _gh_curl "https://api.github.com/repos/$github/releases?per_page=20" \
    | "$VENV_PY" - "$installed" <<'PYEOF'
import sys, json
from packaging.version import Version

installed = Version(sys.argv[1])
try:
    releases = json.load(sys.stdin)
except Exception:
    sys.exit(0)

newer = [r for r in releases
         if r.get('tag_name') and
            _tag_ok(r['tag_name'])]
def _tag_ok(tag):
    try: return Version(tag.lstrip('v')) > installed
    except: return False
newer = [r for r in releases if _tag_ok(r.get('tag_name',''))]
newer.sort(key=lambda r: Version(r['tag_name'].lstrip('v')))

for r in newer:
    tag  = r['tag_name']
    date = r['published_at'][:10]
    url  = r['html_url']
    body = (r.get('body') or '').strip()
    print(f"\n    \033[1m{tag}\033[0m  ({date})")
    if body:
        lines = body.split('\n')
        # skip blank leading lines
        while lines and not lines[0].strip():
            lines.pop(0)
        for line in lines[:25]:
            print(f"    {line}")
        if len(lines) > 25:
            print(f"    \033[2m... {len(lines)-25} more lines — {url}\033[0m")
    else:
        print(f"    (no release notes — {url})")
PYEOF
}

check_pypi() {
  local label=$1 pkg=$2 github=$3
  local installed latest
  installed=$(venv_version "$pkg")
  if [[ -z "$installed" ]]; then
    printf "  ${YELLOW}?${NC}  %-22s not found in venv\n" "$label"
    return
  fi
  latest=$(pypi_latest "$pkg")
  if [[ "$latest" == "?" ]]; then
    printf "  ${YELLOW}?${NC}  %-22s installed=%-12s  fetch failed\n" "$label" "$installed"
  elif [[ "$installed" == "$latest" ]]; then
    printf "  ${GREEN}✓${NC}  %-22s %-12s current\n" "$label" "$installed"
  else
    printf "  ${RED}↑${NC}  %-22s %-12s → %s\n" "$label" "$installed" "$latest"
    UPGRADES=$((UPGRADES + 1))
    show_changelog "$github" "$installed"
    echo ""
  fi
}

check_npm() {
  local label=$1 pkg=$2
  local latest
  latest=$(npm_latest "$pkg")
  printf "  ${GREEN}·${NC}  %-22s latest=%-10s  auto via npx\n" "$label" "$latest"
}

check_git() {
  local label=$1 github=$2
  local head
  head=$(gh_head "$github")
  printf "  ${GREEN}·${NC}  %-22s HEAD=%s  auto via uvx\n" "$label" "$head"
}

echo ""
printf "${BOLD}Stack Freshness — $(date '+%Y-%m-%d %H:%M')${NC}\n"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "PyPI  (pinned in venv — needs explicit upgrade):"
check_pypi "jcodemunch-mcp" "jcodemunch-mcp" "jgravelle/jcodemunch-mcp"
check_pypi "jdatamunch-mcp" "jdatamunch-mcp" "jgravelle/jdatamunch-mcp"
check_pypi "jdocmunch-mcp"  "jdocmunch-mcp"  "jgravelle/jdocmunch-mcp"
check_pypi "mempalace"      "mempalace"      "MemPalace/mempalace"

echo ""
echo "npm   (fetched fresh via npx on each run):"
check_npm "context7" "@upstash/context7-mcp"

echo ""
echo "git   (fetched from HEAD via uvx on each run):"
check_git "serena" "oraios/serena"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ $UPGRADES -gt 0 ]]; then
  echo ""
  printf "${BOLD}To upgrade:${NC}\n"
  echo "  cd $PROJ_ROOT && uv pip install --upgrade \\"
  echo "    jcodemunch-mcp jdatamunch-mcp jdocmunch-mcp mempalace"
fi

echo ""
printf "${BOLD}GitHub Watches (→ Watch → Custom → Releases):${NC}\n"
echo "  https://github.com/jgravelle/jcodemunch-mcp"
echo "  https://github.com/jgravelle/jdatamunch-mcp"
echo "  https://github.com/jgravelle/jdocmunch-mcp"
echo "  https://github.com/MemPalace/mempalace"
echo "  https://github.com/oraios/serena"
echo "  https://github.com/upstash/context7"
echo ""
[[ -z "${GITHUB_TOKEN:-}" ]] && \
  printf "${YELLOW}Tip:${NC} export GITHUB_TOKEN=<pat> to raise GitHub API rate limit (60→5000 req/hr)\n"

exit $(( UPGRADES > 0 ? 1 : 0 ))
