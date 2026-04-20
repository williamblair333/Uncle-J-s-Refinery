<#
.SYNOPSIS
    Installs the three Windows prerequisites missing after install.ps1:
    Git (for Serena), Node.js LTS (for Context7), Claude Code CLI (for
    auto-registration).

.DESCRIPTION
    Uses winget (ships with Windows 10 21H2+ / Windows 11). Each package
    is only installed if its command is not already on PATH.

.NOTES
    Run from an elevated OR normal PowerShell:
        powershell -ExecutionPolicy Bypass -File .\prerequisites.ps1

    After it completes, OPEN A NEW POWERSHELL WINDOW so PATH refreshes,
    then run:
        .\finish-install.ps1
        .\verify.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipGit,
    [switch]$SkipNode,
    [switch]$SkipClaude
)

$ErrorActionPreference = 'Stop'

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "    !!  $m" -ForegroundColor Yellow }
function Has-Cmd    { param($n) [bool](Get-Command $n -ErrorAction SilentlyContinue) }

# Make the uv we already installed visible to this session so Has-Cmd 'uv'
# returns $true if the user already ran install.ps1.
if (Test-Path "$env:USERPROFILE\.local\bin\uv.exe") {
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Step "Checking winget"
if (-not (Has-Cmd 'winget')) {
    throw @"
winget not found. Either:
  1. Update Windows (winget ships with Windows 10 21H2+ / 11).
  2. Install manually: https://aka.ms/getwinget
  3. Install the three prereqs yourself:
       Git for Windows : https://git-scm.com/download/win
       Node.js LTS     : https://nodejs.org
       Claude Code     : https://github.com/anthropics/claude-code
"@
}
Write-OK "winget present"

# --- Git -------------------------------------------------------------------
if ($SkipGit) {
    Write-Warn2 "-SkipGit set; skipping Git install"
} elseif (Has-Cmd 'git') {
    Write-OK "git already installed: $(git --version)"
} else {
    Write-Step "Installing Git (Git.Git) via winget"
    winget install -e --id Git.Git --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "winget exited $LASTEXITCODE for Git.Git" }
    else { Write-OK "Git installed" }
}

# --- Node.js LTS -----------------------------------------------------------
if ($SkipNode) {
    Write-Warn2 "-SkipNode set; skipping Node install"
} elseif (Has-Cmd 'node') {
    Write-OK "node already installed: $(node --version)"
} else {
    Write-Step "Installing Node.js LTS (OpenJS.NodeJS.LTS) via winget"
    winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "winget exited $LASTEXITCODE for OpenJS.NodeJS.LTS" }
    else { Write-OK "Node.js installed" }
}

# --- Claude Code CLI -------------------------------------------------------
if ($SkipClaude) {
    Write-Warn2 "-SkipClaude set; skipping Claude Code install"
} elseif (Has-Cmd 'claude') {
    Write-OK "claude already installed"
} else {
    Write-Step "Installing Claude Code (Anthropic.ClaudeCode) via winget"
    winget install -e --id Anthropic.ClaudeCode --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "winget exited $LASTEXITCODE for Anthropic.ClaudeCode"
        Write-Warn2 "Fallback: after Node is installed, you can run: npm install -g @anthropic-ai/claude-code"
    } else { Write-OK "Claude Code CLI installed" }
}

Write-Step "Prerequisites phase complete"
Write-Host @"

IMPORTANT: open a NEW PowerShell window before running the next step, so
PATH picks up git / node / npx / claude. Then:

  cd C:\Users\wblair\Downloads\claude\_stack_setup
  .\finish-install.ps1         # re-caches Serena (needs git), auto-registers with claude CLI
  .\verify.ps1                 # should now report all PASS

If 'winget' succeeded but a command still isn't found in the new shell,
reboot once. Windows occasionally needs a login refresh for PATH changes
from winget installers.

"@ -ForegroundColor White
