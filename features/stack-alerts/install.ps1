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
