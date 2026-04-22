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

if (-not $message -or -not $packages) {
    Write-Log "ERROR: Claude response missing 'message' or 'packages'. No pitch sent."
    exit 0
}

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
