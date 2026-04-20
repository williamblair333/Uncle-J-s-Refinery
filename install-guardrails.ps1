<#
.SYNOPSIS
    Install dwarvesf/claude-guardrails the correct way -- by invoking
    the upstream install.sh via Git Bash.

.DESCRIPTION
    The previous in-place copy logic was wrong because the repo layout
    is: scan scripts live at `full/*.sh`, not under `full/.claude/`.
    Also, the upstream install.sh uses jq to do a careful deep-merge
    of settings.json that preserves existing hooks (like the jcodemunch
    hooks already in your ~/.claude/settings.json). Re-implementing
    that merge in PowerShell is error-prone.

    This wrapper:
      1. Ensures jq is installed (winget stedolan.jq).
      2. Ensures Git Bash is available (bash.exe shipped with Git for
         Windows).
      3. Backs up ~/.claude/settings.json and ~/.claude/CLAUDE.md.
      4. Runs `bash install.sh full` from the cloned repo.
      5. Reports the outcome.

.PARAMETER Variant
    'full' (default) or 'lite'. Full includes the PostToolUse prompt-
    injection defender; lite skips it.

.PARAMETER SkipJqInstall
    Don't try to install jq. Only useful if you already have jq via some
    other package manager.

.NOTES
    Idempotent. Safe to re-run.
#>

[CmdletBinding()]
param(
    [ValidateSet('full','lite')]
    [string]$Variant = 'full',
    [switch]$SkipJqInstall
)

$ErrorActionPreference = 'Stop'
$StackRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoDir   = Join-Path $StackRoot 'claude-guardrails'
$ClaudeDir = Join-Path $env:USERPROFILE '.claude'

# --- PATH self-heal --------------------------------------------------------
try {
    $m = [System.Environment]::GetEnvironmentVariable('Path','Machine')
    $u = [System.Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$m;$u"
} catch { }

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "    !!  $m" -ForegroundColor Yellow }
function Has-Cmd    { param($n) [bool](Get-Command $n -ErrorAction SilentlyContinue) }

# --- 1. jq -----------------------------------------------------------------
# jq's winget id migrated from stedolan.jq -> jqlang.jq around 2024. Try
# the current id first, fall back to the legacy id, then to a direct
# download if both fail (winget repo can be out of date in fresh VMs).
if (-not $SkipJqInstall) {
    if (Has-Cmd jq) {
        Write-OK "jq already installed: $((jq --version))"
    } else {
        $jqInstalled = $false

        foreach ($id in @('jqlang.jq','stedolan.jq')) {
            Write-Step "Trying winget install -e --id $id"
            winget install -e --id $id --accept-package-agreements --accept-source-agreements 2>&1 | Out-Host
            if ($LASTEXITCODE -eq 0) {
                $jqInstalled = $true
                Write-OK "installed via $id"
                break
            } else {
                Write-Warn2 "winget exited $LASTEXITCODE for $id"
            }
        }

        # Refresh PATH after winget
        try {
            $m = [System.Environment]::GetEnvironmentVariable('Path','Machine')
            $u = [System.Environment]::GetEnvironmentVariable('Path','User')
            $env:Path = "$m;$u"
        } catch { }

        if (-not $jqInstalled -or -not (Has-Cmd jq)) {
            Write-Step "Falling back to direct download of jq.exe from jqlang releases"
            $jqDir = Join-Path $env:USERPROFILE '.local\bin'
            if (-not (Test-Path $jqDir)) { New-Item -ItemType Directory -Path $jqDir -Force | Out-Null }
            $jqExe = Join-Path $jqDir 'jq.exe'
            $jqUrl = 'https://github.com/jqlang/jq/releases/latest/download/jq-windows-amd64.exe'
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $jqUrl -OutFile $jqExe -ErrorAction Stop
                Write-OK "downloaded jq.exe -> $jqExe"
                # Add to this session's PATH in case ~/.local/bin isn't already on it
                if (-not ($env:Path -split ';' -contains $jqDir)) {
                    $env:Path = "$jqDir;$env:Path"
                }
                # Also add to user PATH persistently
                $userPath = [System.Environment]::GetEnvironmentVariable('Path','User')
                if (-not ($userPath -split ';' -contains $jqDir)) {
                    [System.Environment]::SetEnvironmentVariable('Path', "$jqDir;$userPath", 'User')
                    Write-OK "added $jqDir to user PATH (persistent)"
                }
            } catch {
                throw "Direct download of jq.exe failed: $_"
            }
        }

        if (-not (Has-Cmd jq)) {
            Write-Warn2 "jq installed but still not on PATH in THIS shell."
            Write-Warn2 "Open a NEW PowerShell window and re-run .\install-guardrails.ps1"
            exit 1
        }
        Write-OK "jq available: $((jq --version))"
    }
}

# --- 2. Git Bash -----------------------------------------------------------
# The upstream install.sh is bash. On Windows, we run it via bash.exe
# which ships with Git for Windows at C:\Program Files\Git\bin\bash.exe.
$bashPath = $null
foreach ($p in @(
    'C:\Program Files\Git\bin\bash.exe',
    'C:\Program Files (x86)\Git\bin\bash.exe'
)) {
    if (Test-Path $p) { $bashPath = $p; break }
}
if (-not $bashPath) {
    if (Has-Cmd bash) {
        $bashPath = (Get-Command bash).Source
        Write-OK "bash on PATH: $bashPath"
    } else {
        throw "Git Bash (bash.exe) not found. Run prerequisites.ps1 first or install Git for Windows."
    }
} else {
    Write-OK "Git Bash: $bashPath"
}

# --- 3. Repo present -------------------------------------------------------
if (-not (Test-Path $RepoDir)) {
    Write-Step "Cloning dwarvesf/claude-guardrails"
    if (-not (Has-Cmd git)) { throw "git not on PATH." }
    git clone https://github.com/dwarvesf/claude-guardrails.git $RepoDir
} else {
    Write-Step "claude-guardrails already cloned; pulling latest"
    git -C $RepoDir pull --ff-only
}

# --- 4. Backup existing config --------------------------------------------
Write-Step "Backing up current config"
if (-not (Test-Path $ClaudeDir)) { New-Item -ItemType Directory -Path $ClaudeDir | Out-Null }
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($f in 'settings.json','CLAUDE.md') {
    $src = Join-Path $ClaudeDir $f
    if (Test-Path $src) {
        $dst = "$src.backup.$ts"
        Copy-Item -Path $src -Destination $dst
        Write-OK "backed up $f -> $(Split-Path $dst -Leaf)"
    }
}

# --- 5. Run upstream install.sh -------------------------------------------
Write-Step "Running upstream install.sh $Variant"
# Convert Windows path to MSYS path for bash
$msysRepo = ($RepoDir -replace '\\','/') -replace '^C:','/c'
# Run bash from inside the repo dir so relative paths work
& $bashPath -c "cd '$msysRepo' && ./install.sh $Variant"
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "upstream install.sh exited $LASTEXITCODE -- inspect output above"
    exit $LASTEXITCODE
}

# --- 6. Summary -----------------------------------------------------------
Write-Step "Done"
Write-Host @"

Guardrails installed (variant: $Variant).

Backups saved under:  $ClaudeDir\*.backup.$ts

What's active now (on next Claude Code session):
  * permissions.deny     -- blocks Read/Edit on ~/.ssh, ~/.aws, .env, etc.
  * PreToolUse hooks     -- blocks `rm -rf /`, git push to main, curl|bash, etc.
  * UserPromptSubmit hook-- scans your typed prompts for pasted credentials
                            (AWS keys, GitHub tokens, PEM blocks, BIP39, etc.)
$(if ($Variant -eq 'full') { "  * PostToolUse hook     -- scans Read/WebFetch/Bash/mcp__* output for prompt injection`n"})
IMPORTANT: Start a NEW Claude Code session for the hooks to take effect.

Verify the merge worked:
  jq '.hooks | keys'        $ClaudeDir\settings.json
  jq '.permissions.deny | length'  $ClaudeDir\settings.json

If something looks wrong, restore:
  copy $ClaudeDir\settings.json.backup.$ts  $ClaudeDir\settings.json
  copy $ClaudeDir\CLAUDE.md.backup.$ts       $ClaudeDir\CLAUDE.md

"@ -ForegroundColor White
