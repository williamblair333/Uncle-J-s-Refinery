# Stack Update Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated stack update alert pipeline — daily freshness check → Claude analysis → Telegram inline-button pitch → user tap → automated upgrade — for both Linux/Mac (cron) and Windows (Task Scheduler).

**Architecture:** A notification abstraction layer (`lib/notify.sh`) dispatches to a Telegram implementation today, with other channels (Discord, etc.) as future drop-ins. Two scheduled jobs: `stack-alerts-send` (daily) analyzes changelogs via `claude -p` and sends a pitch if relevant; `stack-alerts-poll` (every 2 min) checks for the user's button tap and invokes `claude --allowed-tools Bash -p` to perform the upgrade. A JSON state file in `state/` coordinates them. Everything is optional — enabled by running `features/stack-alerts/install.sh`.

**Tech Stack:** bash, PowerShell, curl, python3 stdlib (JSON parsing), Telegram Bot API (sendMessage / getUpdates / answerCallbackQuery), claude CLI (`-p`, `--allowed-tools`), uv (package upgrades)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `lib/feature-helpers.sh` | CREATE | `prompt_yes_no`, `write_env_var`, `install_cron`, `remove_cron` |
| `lib/feature-helpers.ps1` | CREATE | Windows equivalents of above |
| `lib/notify.sh` | CREATE | Dispatcher: reads `NOTIFY_CHANNEL`, delegates to impl |
| `lib/notify-telegram.sh` | CREATE | `_tg_send_pitch`, `_tg_poll_reply`, `_tg_send_text` |
| `lib/notify.ps1` | CREATE | Windows dispatcher |
| `lib/notify-telegram.ps1` | CREATE | Windows Telegram implementation |
| `scripts/check-stack-freshness.ps1` | CREATE | Windows port of existing freshness check |
| `scripts/stack-alerts-send.sh` | CREATE | Linux: analyze changelog, send Telegram pitch, write state |
| `scripts/stack-alerts-send.ps1` | CREATE | Windows send job |
| `scripts/stack-alerts-poll.sh` | CREATE | Linux: poll callback, invoke claude to upgrade, clean state |
| `scripts/stack-alerts-poll.ps1` | CREATE | Windows poll job |
| `features/stack-alerts/install.sh` | CREATE | Linux interactive setup + cron install |
| `features/stack-alerts/install.ps1` | CREATE | Windows interactive setup + Task Scheduler |
| `features/stack-alerts/README.md` | CREATE | Feature docs, prerequisites, uninstall |
| `install.sh` | MODIFY | Add optional feature prompt after step 6 |
| `install.ps1` | MODIFY | Add optional feature prompt after step 6 |
| `.gitignore` | MODIFY | Add `state/*.log` |

Tasks must be executed in order — each layer is a dependency of the next.

---

### Task 1: Foundation — directories and gitignore

**Files:**
- Modify: `.gitignore`
- Create dir: `lib/`
- Create dir: `features/stack-alerts/`
- Create dir: `state/` (gitignored at runtime)

- [ ] **Step 1: Create directories**

```bash
mkdir -p /opt/proj/Uncle-J-s-Refinery/lib
mkdir -p /opt/proj/Uncle-J-s-Refinery/features/stack-alerts
mkdir -p /opt/proj/Uncle-J-s-Refinery/state
```

- [ ] **Step 2: Add state log to .gitignore**

In `.gitignore`, find the `# ── Runtime state (not source)` section and add `state/*.log` alongside the existing `*.log` entry:

```
# ── Runtime state (not source) ──────────────────────────────────────────
state/
state/*.log
*.log
```

- [ ] **Step 3: Add a .gitkeep so state/ is tracked as an empty directory**

```bash
touch /opt/proj/Uncle-J-s-Refinery/state/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add lib/ features/ state/.gitkeep .gitignore
git commit -m "chore: scaffold lib/, features/stack-alerts/, state/ for alert pipeline"
```

---

### Task 2: lib/feature-helpers.sh and lib/feature-helpers.ps1

**Files:**
- Create: `lib/feature-helpers.sh`
- Create: `lib/feature-helpers.ps1`

- [ ] **Step 1: Create lib/feature-helpers.sh**

```bash
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
```

- [ ] **Step 2: Create lib/feature-helpers.ps1**

```powershell
# Shared utilities for optional feature installers (Windows).
# Dot-source this file: . "$PSScriptRoot\lib\feature-helpers.ps1"

function Prompt-YesNo {
    param([string]$Question, [string]$Default = "y")
    $hint = if ($Default -eq "y") { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = Read-Host "$Question $hint"
        if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $Default }
        switch ($answer.ToLower()) {
            "y" { return $true  }
            "n" { return $false }
            default { Write-Host "  Please answer y or n." }
        }
    }
}

function Prompt-Value {
    param([string]$Question, [string]$Default = "")
    $prompt = $Question
    if ($Default) { $prompt += " [$Default]" }
    $value = Read-Host $prompt
    if ([string]::IsNullOrWhiteSpace($value)) { $value = $Default }
    return $value
}

# Write or update KEY=VALUE as a user-level Windows environment variable.
function Write-EnvVar {
    param([string]$Key, [string]$Value)
    [Environment]::SetEnvironmentVariable($Key, $Value, "User")
    # Also set in current session so scripts run right after install work.
    Set-Item -Path "Env:\$Key" -Value $Value
}

# Register a Task Scheduler task (idempotent — unregisters first if exists).
function Install-ScheduledTask-Idempotent {
    param(
        [string]$TaskName,
        [string]$ScriptPath,
        [string]$WorkingDir,
        [object]$Trigger   # pass a New-ScheduledTaskTrigger result
    )
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
                 -Argument "-NonInteractive -File `"$ScriptPath`"" `
                 -WorkingDirectory $WorkingDir
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger $Trigger -Settings $settings -RunLevel Highest -Force | Out-Null
}

function Remove-ScheduledTask-Safe {
    param([string]$TaskName)
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}
```

- [ ] **Step 3: Make feature-helpers.sh executable and commit**

```bash
chmod +x /opt/proj/Uncle-J-s-Refinery/lib/feature-helpers.sh
git add lib/feature-helpers.sh lib/feature-helpers.ps1
git commit -m "feat: add lib/feature-helpers — shared installer utilities (bash + PowerShell)"
```

---

### Task 3: lib/notify.sh and lib/notify-telegram.sh

**Files:**
- Create: `lib/notify.sh`
- Create: `lib/notify-telegram.sh`

- [ ] **Step 1: Create lib/notify-telegram.sh**

This file implements three functions. All Python JSON work uses temp files to avoid the heredoc/pipe stdin conflict.

```bash
#!/usr/bin/env bash
# Telegram notification backend. Sourced by lib/notify.sh — do not execute directly.
# Requires: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in environment.

_TG_API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
_TG_PY=$(command -v python3)

# Send a message with inline keyboard buttons.
# Args: $1=message text, $2=keyboard JSON array (e.g. '[[{"text":"✅ Yes","callback_data":"approve"}]]')
# Stdout: message_id of the sent message
_tg_send_pitch() {
  local message=$1 keyboard_json=$2
  local tmppy tmppayload response
  tmppy=$(mktemp /tmp/tg_pitch_XXXXXX.py)
  tmppayload=$(mktemp /tmp/tg_payload_XXXXXX.json)

  cat > "$tmppy" << 'PYEOF'
import json, sys
chat_id, message, keyboard_str, out_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
payload = {
    "chat_id": chat_id,
    "text": message,
    "parse_mode": "HTML",
    "reply_markup": {"inline_keyboard": json.loads(keyboard_str)}
}
with open(out_file, "w") as f:
    json.dump(payload, f)
PYEOF

  "$_TG_PY" "$tmppy" "$TELEGRAM_CHAT_ID" "$message" "$keyboard_json" "$tmppayload"
  rm -f "$tmppy"

  response=$(curl -sf -X POST "${_TG_API}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "@${tmppayload}" 2>/dev/null)
  rm -f "$tmppayload"

  echo "$response" | "$_TG_PY" -c "import sys,json; print(json.load(sys.stdin)['result']['message_id'])"
}

# Poll for a callback query on a specific message.
# Args: $1=message_id
# Stdout: "approved" | "rejected" | "pending"
# Side-effect: calls answerCallbackQuery to dismiss loading indicator if found.
_tg_poll_reply() {
  local message_id=$1
  local tmpjson tmppy result callback_query_id

  tmpjson=$(mktemp /tmp/tg_updates_XXXXXX.json)
  tmppy=$(mktemp /tmp/tg_poll_XXXXXX.py)

  curl -sf "${_TG_API}/getUpdates?allowed_updates=callback_query&limit=100" \
    > "$tmpjson" 2>/dev/null || echo '{"result":[]}' > "$tmpjson"

  cat > "$tmppy" << 'PYEOF'
import sys, json
target_msg_id = int(sys.argv[1])
with open(sys.argv[2]) as f:
    updates = json.load(f)
for update in updates.get("result", []):
    cq = update.get("callback_query", {})
    if not cq:
        continue
    if cq.get("message", {}).get("message_id") == target_msg_id:
        print(cq.get("data", "skip"))   # "approve" or "skip"
        print(cq.get("id", ""))         # callback_query_id on second line
        sys.exit(0)
print("pending")
print("")
PYEOF

  result=$("$_TG_PY" "$tmppy" "$message_id" "$tmpjson")
  rm -f "$tmpjson" "$tmppy"

  local data callback_id
  data=$(echo "$result" | sed -n '1p')
  callback_id=$(echo "$result" | sed -n '2p')

  # Acknowledge callback to dismiss Telegram's loading indicator
  if [[ -n "$callback_id" && "$data" != "pending" ]]; then
    curl -sf -X POST "${_TG_API}/answerCallbackQuery" \
      -H "Content-Type: application/json" \
      -d "{\"callback_query_id\":\"${callback_id}\"}" > /dev/null 2>&1 || true
  fi

  if [[ "$data" == "approve" ]]; then
    echo "approved"
  elif [[ "$data" == "pending" ]]; then
    echo "pending"
  else
    echo "rejected"
  fi
}

# Send a plain text message (confirmations, errors).
# Args: $1=message text
_tg_send_text() {
  local message=$1 tmppy tmppayload
  tmppy=$(mktemp /tmp/tg_text_XXXXXX.py)
  tmppayload=$(mktemp /tmp/tg_textpayload_XXXXXX.json)

  cat > "$tmppy" << 'PYEOF'
import json, sys
with open(sys.argv[2], "w") as f:
    json.dump({"chat_id": sys.argv[1], "text": sys.argv[3], "parse_mode": "HTML"}, f)
PYEOF

  "$_TG_PY" "$tmppy" "$TELEGRAM_CHAT_ID" "$tmppayload" "$message"
  rm -f "$tmppy"

  curl -sf -X POST "${_TG_API}/sendMessage" \
    -H "Content-Type: application/json" \
    -d "@${tmppayload}" > /dev/null 2>&1 || true
  rm -f "$tmppayload"
}
```

- [ ] **Step 2: Create lib/notify.sh**

```bash
#!/usr/bin/env bash
# Notification dispatcher. Source this file in alert scripts.
# Reads NOTIFY_CHANNEL (default: telegram) and delegates to the implementation.

_NOTIFY_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

notify_send_pitch() {
  local message=$1 keyboard_json=$2
  case "${NOTIFY_CHANNEL:-telegram}" in
    telegram)
      # shellcheck source=lib/notify-telegram.sh
      source "$_NOTIFY_LIB_DIR/notify-telegram.sh"
      _tg_send_pitch "$message" "$keyboard_json"
      ;;
    *)
      echo "[notify] Unknown NOTIFY_CHANNEL: ${NOTIFY_CHANNEL}" >&2
      return 1
      ;;
  esac
}

notify_poll_reply() {
  local message_id=$1
  case "${NOTIFY_CHANNEL:-telegram}" in
    telegram)
      source "$_NOTIFY_LIB_DIR/notify-telegram.sh"
      _tg_poll_reply "$message_id"
      ;;
    *)
      echo "[notify] Unknown NOTIFY_CHANNEL: ${NOTIFY_CHANNEL}" >&2
      return 1
      ;;
  esac
}

notify_send_text() {
  local message=$1
  case "${NOTIFY_CHANNEL:-telegram}" in
    telegram)
      source "$_NOTIFY_LIB_DIR/notify-telegram.sh"
      _tg_send_text "$message"
      ;;
    *)
      echo "[notify] Unknown NOTIFY_CHANNEL: ${NOTIFY_CHANNEL}" >&2
      return 1
      ;;
  esac
}
```

- [ ] **Step 3: Smoke-test notify-telegram.sh manually**

With `.env` populated (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set), run:

```bash
cd /opt/proj/Uncle-J-s-Refinery
set -a; source .env; set +a
source lib/notify.sh
notify_send_text "🧪 Uncle J notify layer smoke test"
```

Expected: message appears in your Telegram bot chat. No errors on stdout.

- [ ] **Step 4: Make executable and commit**

```bash
chmod +x lib/notify.sh lib/notify-telegram.sh
git add lib/notify.sh lib/notify-telegram.sh
git commit -m "feat: add lib/notify — channel abstraction + Telegram backend (Linux)"
```

---

### Task 4: lib/notify.ps1 and lib/notify-telegram.ps1

**Files:**
- Create: `lib/notify.ps1`
- Create: `lib/notify-telegram.ps1`

- [ ] **Step 1: Create lib/notify-telegram.ps1**

```powershell
# Telegram notification backend for Windows. Dot-sourced by notify.ps1.
# Requires env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

function Get-TgApi { return "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN" }

# Send a pitch message with inline keyboard. Returns message_id.
function _Tg-SendPitch {
    param([string]$Message, [string]$KeyboardJson)
    $api  = Get-TgApi
    $body = @{
        chat_id      = $env:TELEGRAM_CHAT_ID
        text         = $Message
        parse_mode   = "HTML"
        reply_markup = @{ inline_keyboard = ($KeyboardJson | ConvertFrom-Json) }
    } | ConvertTo-Json -Depth 10 -Compress

    $resp = Invoke-RestMethod -Uri "$api/sendMessage" -Method Post `
              -ContentType "application/json" -Body $body
    return $resp.result.message_id
}

# Poll for callback query on a specific message_id.
# Returns "approved", "rejected", or "pending".
function _Tg-PollReply {
    param([long]$MessageId)
    $api  = Get-TgApi
    try {
        $resp = Invoke-RestMethod -Uri "$api/getUpdates?allowed_updates=callback_query&limit=100"
    } catch {
        return "pending"
    }

    foreach ($update in $resp.result) {
        $cq = $update.callback_query
        if (-not $cq) { continue }
        if ($cq.message.message_id -eq $MessageId) {
            # Acknowledge to dismiss loading indicator
            try {
                Invoke-RestMethod -Uri "$api/answerCallbackQuery" -Method Post `
                    -ContentType "application/json" `
                    -Body (@{ callback_query_id = $cq.id } | ConvertTo-Json) | Out-Null
            } catch {}
            return if ($cq.data -eq "approve") { "approved" } else { "rejected" }
        }
    }
    return "pending"
}

# Send a plain text message.
function _Tg-SendText {
    param([string]$Message)
    $api  = Get-TgApi
    $body = @{
        chat_id    = $env:TELEGRAM_CHAT_ID
        text       = $Message
        parse_mode = "HTML"
    } | ConvertTo-Json -Compress
    try {
        Invoke-RestMethod -Uri "$api/sendMessage" -Method Post `
            -ContentType "application/json" -Body $body | Out-Null
    } catch {}
}
```

- [ ] **Step 2: Create lib/notify.ps1**

```powershell
# Notification dispatcher for Windows. Dot-source this in alert scripts.
# Reads NOTIFY_CHANNEL env var (default: telegram).

$_NotifyLibDir = $PSScriptRoot

function Invoke-NotifySendPitch {
    param([string]$Message, [string]$KeyboardJson)
    switch ($env:NOTIFY_CHANNEL ?? "telegram") {
        "telegram" {
            . "$_NotifyLibDir\notify-telegram.ps1"
            return _Tg-SendPitch -Message $Message -KeyboardJson $KeyboardJson
        }
        default { Write-Error "[notify] Unknown NOTIFY_CHANNEL: $env:NOTIFY_CHANNEL"; return $null }
    }
}

function Invoke-NotifyPollReply {
    param([long]$MessageId)
    switch ($env:NOTIFY_CHANNEL ?? "telegram") {
        "telegram" {
            . "$_NotifyLibDir\notify-telegram.ps1"
            return _Tg-PollReply -MessageId $MessageId
        }
        default { Write-Error "[notify] Unknown NOTIFY_CHANNEL: $env:NOTIFY_CHANNEL"; return "pending" }
    }
}

function Invoke-NotifySendText {
    param([string]$Message)
    switch ($env:NOTIFY_CHANNEL ?? "telegram") {
        "telegram" {
            . "$_NotifyLibDir\notify-telegram.ps1"
            _Tg-SendText -Message $Message
        }
        default { Write-Error "[notify] Unknown NOTIFY_CHANNEL: $env:NOTIFY_CHANNEL" }
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add lib/notify.ps1 lib/notify-telegram.ps1
git commit -m "feat: add lib/notify Windows port (PowerShell + Telegram backend)"
```

---

### Task 5: scripts/check-stack-freshness.ps1

**Files:**
- Create: `scripts/check-stack-freshness.ps1`

This is a full Windows port of `scripts/check-stack-freshness.sh`. Uses `Invoke-RestMethod` for API calls and `[System.Version]` for comparison.

- [ ] **Step 1: Create scripts/check-stack-freshness.ps1**

```powershell
<#
.SYNOPSIS
    Checks installed vs latest versions of all MCP stack tools.
    Exits 0 if current, 1 if any PyPI upgrades available.
.PARAMETER Changes
    If set, fetches and prints release notes for behind packages.
#>
param([switch]$Changes)

$ScriptDir  = $PSScriptRoot
$ProjRoot   = Split-Path $ScriptDir -Parent
$VenvPy     = Join-Path $ProjRoot ".venv\Scripts\python.exe"

$RED    = "`e[31m"; $GREEN = "`e[32m"; $YELLOW = "`e[33m"
$BOLD   = "`e[1m";  $DIM   = "`e[2m";  $NC     = "`e[0m"

$upgrades = 0

function Get-VenvVersion([string]$pkg) {
    try {
        $v = & $VenvPy -c "import importlib.metadata; print(importlib.metadata.version('$pkg'))" 2>$null
        return $v.Trim()
    } catch { return "" }
}

function Get-PypiLatest([string]$pkg) {
    try {
        $r = Invoke-RestMethod "https://pypi.org/pypi/$pkg/json" -TimeoutSec 10
        return $r.info.version
    } catch { return "?" }
}

function Get-NpmLatest([string]$pkg) {
    try {
        return (npm view $pkg version 2>$null).Trim()
    } catch { return "?" }
}

function Get-GhHead([string]$repo) {
    try {
        $h = @{ "Accept" = "application/vnd.github.v3+json" }
        if ($env:GITHUB_TOKEN) { $h["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
        $r = Invoke-RestMethod "https://api.github.com/repos/$repo/commits/HEAD" `
               -Headers $h -TimeoutSec 10
        return "$($r.sha.Substring(0,7))  $($r.commit.committer.date.Substring(0,10))"
    } catch { return "?" }
}

function Show-Changelog([string]$repo, [string]$installed) {
    try {
        $h = @{ "Accept" = "application/vnd.github.v3+json" }
        if ($env:GITHUB_TOKEN) { $h["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
        $releases = Invoke-RestMethod `
            "https://api.github.com/repos/$repo/releases?per_page=20" `
            -Headers $h -TimeoutSec 10
    } catch { return }

    $instVer = [System.Version]::new(($installed -replace '^v',''))
    $newer = $releases | Where-Object {
        try { [System.Version]::new(($_.tag_name -replace '^v','')) -gt $instVer } catch { $false }
    } | Sort-Object { [System.Version]::new(($_.tag_name -replace '^v','')) }

    foreach ($r in $newer) {
        Write-Host ""
        Write-Host "    ${BOLD}$($r.tag_name)${NC}  ($($r.published_at.Substring(0,10)))"
        if ($r.body) {
            $lines = $r.body -split "`n" | Where-Object { $_.Trim() }
            $shown = $lines | Select-Object -First 25
            foreach ($l in $shown) { Write-Host "    $l" }
            if ($lines.Count -gt 25) {
                Write-Host "    ${DIM}... $($lines.Count - 25) more lines — $($r.html_url)${NC}"
            }
        } else {
            Write-Host "    (no release notes — $($r.html_url))"
        }
    }
}

function Check-Pypi([string]$label, [string]$pkg, [string]$github) {
    $installed = Get-VenvVersion $pkg
    if (-not $installed) {
        Write-Host "  ${YELLOW}?${NC}  $($label.PadRight(22)) not found in venv"
        return
    }
    $latest = Get-PypiLatest $pkg
    if ($latest -eq "?") {
        Write-Host "  ${YELLOW}?${NC}  $($label.PadRight(22)) installed=$installed  fetch failed"
    } elseif ($installed -eq $latest) {
        Write-Host "  ${GREEN}✓${NC}  $($label.PadRight(22)) $($installed.PadRight(12)) current"
    } else {
        Write-Host "  ${RED}↑${NC}  $($label.PadRight(22)) $($installed.PadRight(12)) → $latest"
        $script:upgrades++
        if ($Changes) { Show-Changelog $github $installed }
        Write-Host ""
    }
}

function Check-Npm([string]$label, [string]$pkg) {
    $latest = Get-NpmLatest $pkg
    Write-Host "  ${GREEN}·${NC}  $($label.PadRight(22)) latest=$($latest.PadRight(10))  auto via npx"
}

function Check-Git([string]$label, [string]$repo) {
    $head = Get-GhHead $repo
    Write-Host "  ${GREEN}·${NC}  $($label.PadRight(22)) HEAD=$head  auto via uvx"
}

Write-Host ""
Write-Host "${BOLD}Stack Freshness — $(Get-Date -Format 'yyyy-MM-dd HH:mm')${NC}"
Write-Host ("━" * 68)
Write-Host ""
Write-Host "PyPI  (pinned in venv — needs explicit upgrade):"
Check-Pypi "jcodemunch-mcp" "jcodemunch-mcp" "jgravelle/jcodemunch-mcp"
Check-Pypi "jdatamunch-mcp" "jdatamunch-mcp" "jgravelle/jdatamunch-mcp"
Check-Pypi "jdocmunch-mcp"  "jdocmunch-mcp"  "jgravelle/jdocmunch-mcp"
Check-Pypi "mempalace"      "mempalace"      "MemPalace/mempalace"
Write-Host ""
Write-Host "npm   (fetched fresh via npx on each run):"
Check-Npm "context7" "@upstash/context7-mcp"
Write-Host ""
Write-Host "git   (fetched from HEAD via uvx on each run):"
Check-Git "serena" "oraios/serena"
Write-Host ""
Write-Host ("━" * 68)

if ($upgrades -gt 0) {
    Write-Host ""
    Write-Host "${BOLD}To upgrade:${NC}"
    Write-Host "  cd $ProjRoot && uv pip install --upgrade ``"
    Write-Host "    jcodemunch-mcp jdatamunch-mcp jdocmunch-mcp mempalace"
}

Write-Host ""
Write-Host "${BOLD}GitHub Watches (→ Watch → Custom → Releases):${NC}"
@(
    "https://github.com/jgravelle/jcodemunch-mcp"
    "https://github.com/jgravelle/jdatamunch-mcp"
    "https://github.com/jgravelle/jdocmunch-mcp"
    "https://github.com/MemPalace/mempalace"
    "https://github.com/oraios/serena"
    "https://github.com/upstash/context7"
) | ForEach-Object { Write-Host "  $_" }
Write-Host ""

exit $(if ($upgrades -gt 0) { 1 } else { 0 })
```

- [ ] **Step 2: Commit**

```bash
git add scripts/check-stack-freshness.ps1
git commit -m "feat: add scripts/check-stack-freshness.ps1 — Windows port of freshness check"
```

---

### Task 6: scripts/stack-alerts-send.sh

**Files:**
- Create: `scripts/stack-alerts-send.sh`

- [ ] **Step 1: Create scripts/stack-alerts-send.sh**

```bash
#!/usr/bin/env bash
# Daily send job: check for stack updates, analyze with Claude, pitch via Telegram.
# Cron runs this; stdout/stderr go to state/stack-alerts.log.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJ_ROOT/state/stack-alerts-pending.json"
LOG_FILE="$PROJ_ROOT/state/stack-alerts.log"
ENV_FILE="$PROJ_ROOT/.env"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

mkdir -p "$PROJ_ROOT/state"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

# Load config
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

# Source notify abstraction
source "$PROJ_ROOT/lib/notify.sh"

# Idempotency guard — don't send if a pitch is already pending
if [[ -f "$STATE_FILE" ]]; then
  log "Pending state exists — skipping send (user hasn't responded yet)."
  exit 0
fi

log "Running freshness check..."
freshness_output=$(bash "$SCRIPT_DIR/check-stack-freshness.sh" 2>&1) || true
freshness_exit=$?

if [[ $freshness_exit -eq 0 ]]; then
  log "All packages current. Nothing to pitch."
  exit 0
fi

log "Updates detected. Invoking Claude for relevance analysis..."

prompt="You are analyzing MCP stack updates for the Uncle J's Refinery project.
This project is a Claude Code harness that relies on jcodemunch, jdatamunch, jdocmunch,
mempalace, serena, and context7 as core retrieval and memory tools.

Freshness check output:
${freshness_output}

If any update contains something meaningful to this project (new tools, behavior changes,
bug fixes that could affect us, breaking changes), respond with ONLY this JSON — no other text:
{\"relevant\":true,\"message\":\"<pitch ≤280 chars: name the packages and explain the impact>\",\"packages\":[\"pkg-name\"]}

If nothing is meaningfully relevant (trivial internals, unrelated platforms, cosmetic), respond ONLY:
{\"relevant\":false}"

analysis=$("$CLAUDE_BIN" -p "$prompt" 2>/dev/null) || {
  log "ERROR: claude -p invocation failed. No pitch sent."
  exit 0
}

relevant=$(echo "$analysis" | python3 -c \
  "import sys,json; d=json.loads(sys.stdin.read()); print(str(d.get('relevant',False)).lower())" \
  2>/dev/null || echo "false")

if [[ "$relevant" != "true" ]]; then
  log "Claude: updates not relevant to this project. No pitch sent."
  exit 0
fi

message=$(echo "$analysis" | python3 -c \
  "import sys,json; print(json.loads(sys.stdin.read())['message'])" 2>/dev/null)
packages=$(echo "$analysis" | python3 -c \
  "import sys,json; print(json.dumps(json.loads(sys.stdin.read())['packages']))" 2>/dev/null)

keyboard='[[{"text":"✅ Upgrade","callback_data":"approve"},{"text":"❌ Skip","callback_data":"skip"}]]'

log "Sending Telegram pitch..."
message_id=$(notify_send_pitch "$message" "$keyboard") || {
  log "ERROR: Telegram send failed. No state written."
  exit 0
}

# Write pending state
python3 - "$message_id" "$packages" << 'PYEOF' > "$STATE_FILE"
import sys, json, datetime
state = {
    "message_id": int(sys.argv[1]),
    "sent_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "packages": json.loads(sys.argv[2])
}
print(json.dumps(state, indent=2))
PYEOF

log "Pitch sent (message_id=${message_id}). Waiting for user response."
```

- [ ] **Step 2: Make executable and do a dry-run test**

```bash
chmod +x scripts/stack-alerts-send.sh
# Dry-run: set dummy env and check for syntax errors only
bash -n scripts/stack-alerts-send.sh && echo "Syntax OK"
```

Expected: `Syntax OK` — no output errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/stack-alerts-send.sh
git commit -m "feat: add scripts/stack-alerts-send.sh — daily changelog analysis + Telegram pitch"
```

---

### Task 7: scripts/stack-alerts-send.ps1

**Files:**
- Create: `scripts/stack-alerts-send.ps1`

- [ ] **Step 1: Create scripts/stack-alerts-send.ps1**

```powershell
# Daily send job (Windows). Checks for stack updates, analyzes with Claude, pitches via Telegram.
param()
$ErrorActionPreference = "Stop"

$ScriptDir  = $PSScriptRoot
$ProjRoot   = Split-Path $ScriptDir -Parent
$StateFile  = Join-Path $ProjRoot "state\stack-alerts-pending.json"
$LogFile    = Join-Path $ProjRoot "state\stack-alerts.log"

New-Item -ItemType Directory -Path (Join-Path $ProjRoot "state") -Force | Out-Null

function Write-Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

. "$ProjRoot\lib\notify.ps1"

# Idempotency guard
if (Test-Path $StateFile) {
    Write-Log "Pending state exists — skipping send."
    exit 0
}

Write-Log "Running freshness check..."
$freshnessOutput = & powershell -NonInteractive -File "$ScriptDir\check-stack-freshness.ps1" 2>&1
$freshnessExit   = $LASTEXITCODE

if ($freshnessExit -eq 0) {
    Write-Log "All packages current. Nothing to pitch."
    exit 0
}

Write-Log "Updates detected. Invoking Claude for relevance analysis..."

$prompt = @"
You are analyzing MCP stack updates for the Uncle J's Refinery project.
This project is a Claude Code harness that relies on jcodemunch, jdatamunch, jdocmunch,
mempalace, serena, and context7 as core retrieval and memory tools.

Freshness check output:
$freshnessOutput

If any update contains something meaningful to this project (new tools, behavior changes,
bug fixes that could affect us, breaking changes), respond with ONLY this JSON — no other text:
{"relevant":true,"message":"<pitch ≤280 chars: name the packages and explain the impact>","packages":["pkg-name"]}

If nothing is meaningfully relevant, respond ONLY:
{"relevant":false}
"@

try {
    $analysis = claude -p $prompt 2>$null
} catch {
    Write-Log "ERROR: claude -p invocation failed. No pitch sent."
    exit 0
}

try {
    $parsed   = $analysis | ConvertFrom-Json
    $relevant = $parsed.relevant
} catch {
    Write-Log "ERROR: Claude response was not valid JSON. No pitch sent."
    exit 0
}

if (-not $relevant) {
    Write-Log "Claude: updates not relevant. No pitch sent."
    exit 0
}

$message  = $parsed.message
$packages = $parsed.packages | ConvertTo-Json -Compress
$keyboard = '[[{"text":"✅ Upgrade","callback_data":"approve"},{"text":"❌ Skip","callback_data":"skip"}]]'

Write-Log "Sending Telegram pitch..."
try {
    $messageId = Invoke-NotifySendPitch -Message $message -KeyboardJson $keyboard
} catch {
    Write-Log "ERROR: Telegram send failed — $_"
    exit 0
}

$state = @{
    message_id = [long]$messageId
    sent_at    = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    packages   = $parsed.packages
}
$state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8

Write-Log "Pitch sent (message_id=$messageId). Waiting for user response."
```

- [ ] **Step 2: Commit**

```bash
git add scripts/stack-alerts-send.ps1
git commit -m "feat: add scripts/stack-alerts-send.ps1 — Windows send job"
```

---

### Task 8: scripts/stack-alerts-poll.sh

**Files:**
- Create: `scripts/stack-alerts-poll.sh`

- [ ] **Step 1: Create scripts/stack-alerts-poll.sh**

```bash
#!/usr/bin/env bash
# Every-2-min poll job: check for user's Telegram reply, upgrade if approved.
# Cron runs this; stdout/stderr go to state/stack-alerts.log.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_FILE="$PROJ_ROOT/state/stack-alerts-pending.json"
LOG_FILE="$PROJ_ROOT/state/stack-alerts.log"
ENV_FILE="$PROJ_ROOT/.env"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "claude")}"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"; }

# No pending state — nothing to do
[[ -f "$STATE_FILE" ]] || exit 0

# Load config
[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

source "$PROJ_ROOT/lib/notify.sh"

# Read state
message_id=$(python3 -c "import sys,json; print(json.load(open('$STATE_FILE'))['message_id'])")
sent_at=$(python3 -c "import sys,json; print(json.load(open('$STATE_FILE'))['sent_at'])")
packages=$(python3 -c "import sys,json; print(json.dumps(json.load(open('$STATE_FILE'))['packages']))")

# Check expiry
expired=$(python3 - "$sent_at" "${ALERT_EXPIRY_MINUTES:-60}" << 'PYEOF'
import sys, datetime
sent_at_str, expiry_min = sys.argv[1], int(sys.argv[2])
sent_at = datetime.datetime.strptime(sent_at_str, "%Y-%m-%dT%H:%M:%SZ")
elapsed = (datetime.datetime.utcnow() - sent_at).total_seconds() / 60
print("true" if elapsed > expiry_min else "false")
PYEOF
)

if [[ "$expired" == "true" ]]; then
  log "Alert window expired (>${ALERT_EXPIRY_MINUTES:-60} min). Cleaning up state."
  rm -f "$STATE_FILE"
  exit 0
fi

reply=$(notify_poll_reply "$message_id")

case "$reply" in
  pending)
    exit 0
    ;;
  rejected)
    log "User skipped upgrade. Cleaning up state."
    rm -f "$STATE_FILE"
    notify_send_text "⏭ Upgrade skipped. Will check again tomorrow." || true
    exit 0
    ;;
  approved)
    log "User approved upgrade. Invoking Claude to upgrade packages..."
    rm -f "$STATE_FILE"

    pkg_list=$(echo "$packages" | python3 -c \
      "import sys,json; print(' '.join(json.loads(sys.stdin.read())))")

    upgrade_prompt="Upgrade these Python packages in the Uncle J's Refinery venv.
Run exactly: cd $PROJ_ROOT && uv pip install --upgrade $pkg_list
Then check if the release notes for these packages require any changes to CLAUDE.md.
Respond with one sentence: what was upgraded and whether CLAUDE.md needed changes."

    result=$("$CLAUDE_BIN" --allowed-tools 'Bash' -p "$upgrade_prompt" 2>/dev/null) || \
      result="Upgrade command failed — check logs and run manually: uv pip install --upgrade $pkg_list"

    log "Upgrade result: $result"
    notify_send_text "🔧 $result" || true
    ;;
esac
```

- [ ] **Step 2: Make executable, syntax check, and commit**

```bash
chmod +x scripts/stack-alerts-poll.sh
bash -n scripts/stack-alerts-poll.sh && echo "Syntax OK"
git add scripts/stack-alerts-poll.sh
git commit -m "feat: add scripts/stack-alerts-poll.sh — 2-min callback poller + upgrade invoker"
```

---

### Task 9: scripts/stack-alerts-poll.ps1

**Files:**
- Create: `scripts/stack-alerts-poll.ps1`

- [ ] **Step 1: Create scripts/stack-alerts-poll.ps1**

```powershell
# Every-2-min poll job (Windows). Checks for Telegram reply, upgrades if approved.
param()
$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = $PSScriptRoot
$ProjRoot  = Split-Path $ScriptDir -Parent
$StateFile = Join-Path $ProjRoot "state\stack-alerts-pending.json"
$LogFile   = Join-Path $ProjRoot "state\stack-alerts.log"

function Write-Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

if (-not (Test-Path $StateFile)) { exit 0 }

. "$ProjRoot\lib\notify.ps1"

$state     = Get-Content $StateFile | ConvertFrom-Json
$messageId = [long]$state.message_id
$sentAt    = [datetime]::ParseExact($state.sent_at, "yyyy-MM-ddTHH:mm:ssZ", $null)
$packages  = $state.packages
$expiryMin = [int]($env:ALERT_EXPIRY_MINUTES ?? "60")

$elapsedMin = ([datetime]::UtcNow - $sentAt).TotalMinutes
if ($elapsedMin -gt $expiryMin) {
    Write-Log "Alert window expired (>$expiryMin min). Cleaning up state."
    Remove-Item $StateFile -Force
    exit 0
}

$reply = Invoke-NotifyPollReply -MessageId $messageId

switch ($reply) {
    "pending"  { exit 0 }
    "rejected" {
        Write-Log "User skipped upgrade. Cleaning up state."
        Remove-Item $StateFile -Force
        Invoke-NotifySendText -Message "⏭ Upgrade skipped. Will check again tomorrow."
        exit 0
    }
    "approved" {
        Write-Log "User approved upgrade. Invoking Claude..."
        Remove-Item $StateFile -Force

        $pkgList = $packages -join " "
        $upgradePrompt = @"
Upgrade these Python packages in the Uncle J's Refinery venv.
Run exactly: cd $ProjRoot && uv pip install --upgrade $pkgList
Then check if the release notes for these packages require any changes to CLAUDE.md.
Respond with one sentence: what was upgraded and whether CLAUDE.md needed changes.
"@
        try {
            $result = claude --allowed-tools Bash -p $upgradePrompt 2>$null
        } catch {
            $result = "Upgrade failed — run manually: uv pip install --upgrade $pkgList"
        }

        Write-Log "Upgrade result: $result"
        Invoke-NotifySendText -Message "🔧 $result"
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add scripts/stack-alerts-poll.ps1
git commit -m "feat: add scripts/stack-alerts-poll.ps1 — Windows poll job"
```

---

### Task 10: features/stack-alerts/install.sh

**Files:**
- Create: `features/stack-alerts/install.sh`

- [ ] **Step 1: Create features/stack-alerts/install.sh**

```bash
#!/usr/bin/env bash
# Interactive setup for stack update alerts (Linux/Mac).
# Usage:
#   bash features/stack-alerts/install.sh            # install
#   bash features/stack-alerts/install.sh --uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJ_ROOT/.env"

source "$PROJ_ROOT/lib/feature-helpers.sh"

step()  { printf '\n==> %s\n' "$*"; }
ok()    { printf '    OK  %s\n' "$*"; }
warn()  { printf '    !!  %s\n' "$*" >&2; }

CRON_MARKER_SEND="uncle-j-stack-alerts-send"
CRON_MARKER_POLL="uncle-j-stack-alerts-poll"

# ── Uninstall mode ──────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
  step "Uninstalling stack alerts"
  remove_cron "$CRON_MARKER_SEND"
  remove_cron "$CRON_MARKER_POLL"
  rm -f "$PROJ_ROOT/state/stack-alerts-pending.json"
  ok "Cron jobs removed and pending state cleared."
  echo ""
  echo "  To also remove secrets, delete these lines from $ENV_FILE:"
  echo "    NOTIFY_CHANNEL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,"
  echo "    ALERT_SEND_TIME, ALERT_EXPIRY_MINUTES"
  exit 0
fi

# ── Dependency check ─────────────────────────────────────────────────────────
step "Checking dependencies"
for cmd in curl jq python3; do
  if ! command -v "$cmd" &>/dev/null; then
    warn "$cmd not found — install it and re-run."
    exit 1
  fi
  ok "$cmd"
done

CLAUDE_BIN=$(command -v claude 2>/dev/null || true)
if [[ -z "$CLAUDE_BIN" ]]; then
  warn "claude CLI not found on PATH — install Claude Code and re-run."
  exit 1
fi
ok "claude at $CLAUDE_BIN"

# ── Config prompts ────────────────────────────────────────────────────────────
step "Configuration"
echo ""
echo "  You need a Telegram bot token and your chat ID."
echo "  Token: message @BotFather → /mybots → select bot → API Token"
echo "  Chat ID: send any message to your bot, then visit:"
echo "    https://api.telegram.org/bot<TOKEN>/getUpdates"
echo "  and look for \"chat\":{\"id\":XXXXXXX}"
echo ""

prompt_value "Telegram bot token" "" TELEGRAM_BOT_TOKEN
[[ -z "$TELEGRAM_BOT_TOKEN" ]] && { warn "Bot token required."; exit 1; }

prompt_value "Telegram chat ID" "" TELEGRAM_CHAT_ID
[[ -z "$TELEGRAM_CHAT_ID" ]] && { warn "Chat ID required."; exit 1; }

prompt_value "Daily send time (24h HH:MM)" "09:00" ALERT_SEND_TIME
prompt_value "Alert expiry window (minutes)" "60"    ALERT_EXPIRY_MINUTES

# ── Write config ──────────────────────────────────────────────────────────────
step "Writing config to $ENV_FILE"
write_env_var "$ENV_FILE" "NOTIFY_CHANNEL"       "telegram"
write_env_var "$ENV_FILE" "TELEGRAM_BOT_TOKEN"   "$TELEGRAM_BOT_TOKEN"
write_env_var "$ENV_FILE" "TELEGRAM_CHAT_ID"     "$TELEGRAM_CHAT_ID"
write_env_var "$ENV_FILE" "ALERT_SEND_TIME"      "$ALERT_SEND_TIME"
write_env_var "$ENV_FILE" "ALERT_EXPIRY_MINUTES" "$ALERT_EXPIRY_MINUTES"
ok ".env updated"

# ── Install cron jobs ─────────────────────────────────────────────────────────
step "Installing cron jobs"

SEND_HOUR=$(echo "$ALERT_SEND_TIME" | cut -d: -f1 | sed 's/^0//')
SEND_MIN=$(echo "$ALERT_SEND_TIME"  | cut -d: -f2 | sed 's/^0//')
[[ -z "$SEND_HOUR" ]] && SEND_HOUR=0
[[ -z "$SEND_MIN"  ]] && SEND_MIN=0

SEND_ENTRY="${SEND_MIN} ${SEND_HOUR} * * * CLAUDE_BIN=${CLAUDE_BIN} cd ${PROJ_ROOT} && bash scripts/stack-alerts-send.sh >> state/stack-alerts.log 2>&1"
POLL_ENTRY="*/2 * * * * CLAUDE_BIN=${CLAUDE_BIN} cd ${PROJ_ROOT} && bash scripts/stack-alerts-poll.sh >> state/stack-alerts.log 2>&1"

install_cron "$CRON_MARKER_SEND" "$SEND_ENTRY"
ok "Send cron: ${SEND_MIN} ${SEND_HOUR} * * *"

install_cron "$CRON_MARKER_POLL" "$POLL_ENTRY"
ok "Poll cron: */2 * * * *"

# ── Smoke test ────────────────────────────────────────────────────────────────
step "Sending test Telegram message"
set -a; source "$ENV_FILE"; set +a
source "$PROJ_ROOT/lib/notify.sh"
notify_send_text "✅ Uncle J's Refinery stack alerts configured. You'll receive upgrade pitches at ${ALERT_SEND_TIME} daily."
ok "Test message sent — check your Telegram."

# ── Summary ───────────────────────────────────────────────────────────────────
step "Done"
echo ""
echo "  Two cron jobs installed:"
echo "    • stack-alerts-send  — daily at ${ALERT_SEND_TIME}"
echo "    • stack-alerts-poll  — every 2 minutes"
echo ""
echo "  To uninstall:  bash features/stack-alerts/install.sh --uninstall"
echo "  Logs:          $PROJ_ROOT/state/stack-alerts.log"
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x features/stack-alerts/install.sh
git add features/stack-alerts/install.sh
git commit -m "feat: add features/stack-alerts/install.sh — interactive Linux setup + cron install"
```

---

### Task 11: features/stack-alerts/install.ps1

**Files:**
- Create: `features/stack-alerts/install.ps1`

- [ ] **Step 1: Create features/stack-alerts/install.ps1**

```powershell
<#
.SYNOPSIS
    Interactive setup for stack update alerts (Windows).
.PARAMETER Uninstall
    Remove Task Scheduler tasks and clear pending state.
#>
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$ProjRoot  = Split-Path (Split-Path $ScriptDir -Parent) -Parent

. "$ProjRoot\lib\feature-helpers.ps1"

function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

$TaskSend = "UncleJ-StackAlerts-Send"
$TaskPoll = "UncleJ-StackAlerts-Poll"

# ── Uninstall ────────────────────────────────────────────────────────────────
if ($Uninstall) {
    Write-Step "Uninstalling stack alerts"
    Remove-ScheduledTask-Safe $TaskSend
    Remove-ScheduledTask-Safe $TaskPoll
    $pending = Join-Path $ProjRoot "state\stack-alerts-pending.json"
    if (Test-Path $pending) { Remove-Item $pending -Force }
    Write-Ok "Tasks removed and pending state cleared."
    Write-Host "`n  To also remove secrets, delete these Windows env vars:"
    Write-Host "    NOTIFY_CHANNEL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,"
    Write-Host "    ALERT_SEND_TIME, ALERT_EXPIRY_MINUTES"
    exit 0
}

# ── Dependency check ─────────────────────────────────────────────────────────
Write-Step "Checking dependencies"
foreach ($cmd in @("curl.exe", "python3")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Warn "$cmd not found — install it and re-run."; exit 1
    }
    Write-Ok $cmd
}
$claudeBin = (Get-Command "claude" -ErrorAction SilentlyContinue)?.Source
if (-not $claudeBin) { Write-Warn "claude CLI not found — install Claude Code and re-run."; exit 1 }
Write-Ok "claude at $claudeBin"

# ── Config prompts ────────────────────────────────────────────────────────────
Write-Step "Configuration"
Write-Host ""
Write-Host "  Token: message @BotFather → /mybots → select bot → API Token"
Write-Host "  Chat ID: send any message to your bot, then visit:"
Write-Host "    https://api.telegram.org/bot<TOKEN>/getUpdates"
Write-Host "  and look for `"chat`":{`"id`":XXXXXXX}"
Write-Host ""

$botToken = Prompt-Value "Telegram bot token"
if (-not $botToken) { Write-Warn "Bot token required."; exit 1 }

$chatId = Prompt-Value "Telegram chat ID"
if (-not $chatId) { Write-Warn "Chat ID required."; exit 1 }

$sendTime  = Prompt-Value "Daily send time (24h HH:MM)" "09:00"
$expiryMin = Prompt-Value "Alert expiry window (minutes)" "60"

# ── Write config ──────────────────────────────────────────────────────────────
Write-Step "Writing config to Windows environment variables"
Write-EnvVar "NOTIFY_CHANNEL"       "telegram"
Write-EnvVar "TELEGRAM_BOT_TOKEN"   $botToken
Write-EnvVar "TELEGRAM_CHAT_ID"     $chatId
Write-EnvVar "ALERT_SEND_TIME"      $sendTime
Write-EnvVar "ALERT_EXPIRY_MINUTES" $expiryMin
Write-Ok "Environment variables set (user-level, persistent)"

# ── Install Task Scheduler tasks ──────────────────────────────────────────────
Write-Step "Installing Task Scheduler tasks"

$timeParts = $sendTime -split ":"
$hour = [int]$timeParts[0]; $minute = [int]$timeParts[1]
$dailyTime = (Get-Date -Hour $hour -Minute $minute -Second 0)

$sendScript = Join-Path $ProjRoot "scripts\stack-alerts-send.ps1"
$pollScript = Join-Path $ProjRoot "scripts\stack-alerts-poll.ps1"

$sendTrigger = New-ScheduledTaskTrigger -Daily -At $dailyTime
Install-ScheduledTask-Idempotent -TaskName $TaskSend -ScriptPath $sendScript `
    -WorkingDir $ProjRoot -Trigger $sendTrigger
Write-Ok "Send task: daily at $sendTime"

# Poll: daily at midnight, repeat every 2 min for 24h
$pollTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$pollTrigger.Repetition = (New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Hours 24) -Once -At "00:00").Repetition
Install-ScheduledTask-Idempotent -TaskName $TaskPoll -ScriptPath $pollScript `
    -WorkingDir $ProjRoot -Trigger $pollTrigger
Write-Ok "Poll task: every 2 minutes"

# ── Smoke test ────────────────────────────────────────────────────────────────
Write-Step "Sending test Telegram message"
. "$ProjRoot\lib\notify.ps1"
Invoke-NotifySendText -Message "✅ Uncle J's Refinery stack alerts configured. You'll receive upgrade pitches at $sendTime daily."
Write-Ok "Test message sent — check your Telegram."

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Step "Done"
Write-Host ""
Write-Host "  Two Task Scheduler tasks installed:"
Write-Host "    • $TaskSend — daily at $sendTime"
Write-Host "    • $TaskPoll — every 2 minutes"
Write-Host ""
Write-Host "  To uninstall:  .\features\stack-alerts\install.ps1 -Uninstall"
Write-Host "  Logs:          $ProjRoot\state\stack-alerts.log"
```

- [ ] **Step 2: Commit**

```bash
git add features/stack-alerts/install.ps1
git commit -m "feat: add features/stack-alerts/install.ps1 — Windows setup + Task Scheduler"
```

---

### Task 12: features/stack-alerts/README.md

**Files:**
- Create: `features/stack-alerts/README.md`

- [ ] **Step 1: Create README.md**

```markdown
# Stack Update Alerts

Automated daily check for updates to the MCP stack tools, with Claude analysis
and a Telegram pitch when something relevant lands. You tap ✅ or ❌; Claude
does the rest.

## How It Works

1. **Daily send job** checks `scripts/check-stack-freshness.sh` for new versions.
2. If behind, invokes `claude -p` to analyze changelogs for relevance.
3. If relevant, sends you a Telegram message with ✅ Upgrade / ❌ Skip buttons.
4. **Every-2-min poll job** watches for your tap.
5. ✅ → Claude runs `uv pip install --upgrade` and confirms via Telegram.
6. ❌ or no reply within the expiry window → silently cleaned up.

## Prerequisites

- `curl`, `jq`, `python3` on PATH
- `claude` CLI (Claude Code) on PATH
- A Telegram bot token (from [@BotFather](https://t.me/botfather))
- Your Telegram chat ID

**Finding your chat ID:**
1. Send any message to your bot.
2. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Look for `"chat":{"id":XXXXXXXXX}` in the response.

## Install

**Linux/Mac:**
```bash
bash features/stack-alerts/install.sh
```

**Windows:**
```powershell
.\features\stack-alerts\install.ps1
```

The main `install.sh` / `install.ps1` also offers this as an opt-in prompt.

## Uninstall

**Linux/Mac:**
```bash
bash features/stack-alerts/install.sh --uninstall
```

**Windows:**
```powershell
.\features\stack-alerts\install.ps1 -Uninstall
```

Then remove the five config keys from `.env` (Linux) or Windows user env vars.

## Logs

`state/stack-alerts.log` — appended to by both the send and poll jobs.

## Config Keys

| Key | Description | Default |
|-----|-------------|---------|
| `NOTIFY_CHANNEL` | Notification backend | `telegram` |
| `TELEGRAM_BOT_TOKEN` | From @BotFather | required |
| `TELEGRAM_CHAT_ID` | Your personal chat ID | required |
| `ALERT_SEND_TIME` | Daily pitch time (HH:MM 24h) | `09:00` |
| `ALERT_EXPIRY_MINUTES` | How long buttons stay valid | `60` |

## Adding a New Notification Channel (e.g. Discord)

1. Create `lib/notify-discord.sh` (and `.ps1`) implementing `_discord_send_pitch`,
   `_discord_poll_reply`, `_discord_send_text` with the same signatures as the
   Telegram equivalents.
2. Add a `discord)` case to `lib/notify.sh` (and `notify.ps1`).
3. Set `NOTIFY_CHANNEL=discord` in `.env`.

The alert scripts require no changes.
```

- [ ] **Step 2: Commit**

```bash
git add features/stack-alerts/README.md
git commit -m "docs: add features/stack-alerts/README.md"
```

---

### Task 13: Main install.sh and install.ps1 integration

**Files:**
- Modify: `install.sh` — add optional feature opt-in after step 6
- Modify: `install.ps1` — add optional feature opt-in after step 6

- [ ] **Step 1: Add feature opt-in to install.sh**

At the very end of `install.sh`, after the final `EOF` closing the `cat <<EOF` block, append:

```bash
# --- 7. Optional features ----------------------------------------------------
step "Optional features"
source "$STACK_ROOT/lib/feature-helpers.sh"
echo ""
if prompt_yes_no "Enable automated stack update alerts (Telegram)?"; then
  bash "$STACK_ROOT/features/stack-alerts/install.sh"
fi
```

- [ ] **Step 2: Add feature opt-in to install.ps1**

At the very end of `install.ps1`, after the final `Write-Host` block, append:

```powershell
# --- 7. Optional features -----------------------------------------------------
Write-Step "Optional features"
. "$StackRoot\lib\feature-helpers.ps1"
Write-Host ""
if (Prompt-YesNo "Enable automated stack update alerts (Telegram)?") {
    & "$StackRoot\features\stack-alerts\install.ps1"
}
```

- [ ] **Step 3: Verify install.sh still parses cleanly**

```bash
bash -n /opt/proj/Uncle-J-s-Refinery/install.sh && echo "Syntax OK"
```

Expected: `Syntax OK`

- [ ] **Step 4: Commit**

```bash
git add install.sh install.ps1
git commit -m "feat: add optional stack alert feature prompt to main install.sh / install.ps1"
```

---

### Task 14: End-to-end smoke test (Linux)

No new files — this task validates the full pipeline with real credentials.

- [ ] **Step 1: Populate .env with real Telegram credentials**

```bash
# Edit .env and set:
# TELEGRAM_BOT_TOKEN=<your-token>
# TELEGRAM_CHAT_ID=<your-chat-id>
```

- [ ] **Step 2: Run the feature installer**

```bash
bash features/stack-alerts/install.sh
```

Expected: prompts for config, installs cron jobs, sends a test Telegram message you can see in your chat.

- [ ] **Step 3: Manually trigger the send job**

```bash
cd /opt/proj/Uncle-J-s-Refinery && bash scripts/stack-alerts-send.sh
```

Expected (if packages are behind): Telegram message arrives with ✅ / ❌ buttons. `state/stack-alerts-pending.json` exists.

Expected (if all current): `"All packages current. Nothing to pitch."` in log.

- [ ] **Step 4: Manually trigger the poll job while pending**

```bash
bash scripts/stack-alerts-poll.sh
```

Expected: `"pending"` in log — no state change until you tap a button.

- [ ] **Step 5: Tap ✅ in Telegram, then trigger poll again**

```bash
bash scripts/stack-alerts-poll.sh
```

Expected: log shows `"User approved upgrade"`, Claude upgrade output, Telegram confirmation message. `state/stack-alerts-pending.json` deleted.

- [ ] **Step 6: Final commit (if any fixups were needed)**

```bash
git add -p   # stage any fixes found during smoke test
git commit -m "fix: smoke test corrections for stack alerts pipeline"
```
