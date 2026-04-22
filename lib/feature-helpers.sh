#!/usr/bin/env bash
# Shared utilities for optional feature installers.
# Source this file; do not execute directly.

# Prompt yes/no. Exits 0 for yes, 1 for no.
prompt_yes_no() {
  local question=$1 default=${2:-y} prompt answer
  [[ "$default" == "y" ]] && prompt="[Y/n]" || prompt="[y/N]"
  while true; do
    read -rp "$question $prompt " answer
    answer=${answer:-$default}
    case "${answer,,}" in
      y|yes) return 0 ;;
      n|no)  return 1 ;;
      *) echo "  Please answer y or n." ;;
    esac
  done
}

# Prompt for a value with optional default; store result in named variable.
prompt_value() {
  local question=$1 default=${2:-} varname=$3 prompt value
  prompt="$question"
  [[ -n "$default" ]] && prompt+=" [$default]"
  prompt+=": "
  read -rp "$prompt" value
  printf -v "$varname" '%s' "${value:-$default}"
}

# Write or update KEY=VALUE in an env file. Creates the file if absent.
write_env_var() {
  local file=$1 key=$2 value=$3
  [[ ! -f "$file" ]] && touch "$file"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

# Install a cron entry idempotently using a unique marker comment.
# Usage: install_cron "MARKER" "cron-schedule command"
install_cron() {
  local marker=$1 entry=$2 tmpfile
  tmpfile=$(mktemp)
  # Remove any existing entry for this marker (marker line + command line)
  crontab -l 2>/dev/null \
    | awk -v m="# $marker" '$0==m{skip=1; next} skip{skip=0; next} 1' \
    > "$tmpfile" || true
  { cat "$tmpfile"; echo "# $marker"; echo "$entry"; } | crontab -
  rm -f "$tmpfile"
}

# Remove cron entries installed under a given marker.
remove_cron() {
  local marker=$1 tmpfile
  tmpfile=$(mktemp)
  crontab -l 2>/dev/null \
    | awk -v m="# $marker" '$0==m{skip=1; next} skip{skip=0; next} 1' \
    > "$tmpfile" || true
  crontab "$tmpfile"
  rm -f "$tmpfile"
}
