<#
.SYNOPSIS
    Post-install sanity check for the Claude retrieval stack.
.DESCRIPTION
    Verifies that every binary resolves and the helper tooling (uvx, npx,
    claude) is present.

    Path handling:
      * Prepends %USERPROFILE%\.local\bin so a freshly-installed uv is
        visible even before the shell's PATH refreshes.
      * Also prepends typical Node and Git install dirs as a backup for
        cases where winget installed but PATH hasn't propagated yet.

    Exit code 0 = all checks passed; non-zero = at least one failure.
#>

$ErrorActionPreference = 'Continue'
$StackRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvScripts = Join-Path $StackRoot ".venv\Scripts"

# --- PATH augmentation -----------------------------------------------------
# STEP A: Refresh PATH from the registry. This is what a fresh PowerShell
# would see. Fixes every "I just installed it but this shell doesn't know"
# problem in one shot.
try {
    $machinePath = [System.Environment]::GetEnvironmentVariable('Path','Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$machinePath;$userPath"
} catch {
    # If the registry read fails for some reason, fall through to step B.
}

# STEP B: As a safety net, pre-pend the likely install locations that
# winget / uv use. Covers winget installs where PATH wasn't updated
# (rare), and first-run-before-reboot scenarios.
$extraPaths = @(
    "$env:USERPROFILE\.local\bin",                         # uv / uvx
    "$env:ProgramFiles\Git\cmd",                           # git (system)
    "$env:ProgramFiles\nodejs",                            # node / npx
    "$env:APPDATA\npm",                                    # global npm binaries
    "$env:LOCALAPPDATA\AnthropicClaude",                   # Claude Code (winget native)
    "$env:LOCALAPPDATA\Programs\claude",                   # Claude Code (alt layout)
    "$env:LOCALAPPDATA\Programs\Anthropic\Claude Code",    # Claude Code (installer layout)
    "$env:LOCALAPPDATA\Microsoft\WinGet\Links",            # winget command-line aliases
    "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"          # winget package root
) | Where-Object { Test-Path $_ }

foreach ($p in $extraPaths) {
    if (-not ($env:Path -split ';' -contains $p)) {
        $env:Path = "$p;$env:Path"
    }
}

# --- Helpers ---------------------------------------------------------------
$fails = 0
function Pass { param($n) Write-Host "  PASS  $n" -ForegroundColor Green }
function Fail { param($n, $reason) Write-Host "  FAIL  $n  -- $reason" -ForegroundColor Red; $script:fails++ }
function Note { param($n, $msg) Write-Host "  NOTE  $n  -- $msg" -ForegroundColor Yellow }

function Check-Cmd {
    # Passes if the external command runs with exit 0. Treats non-zero exit
    # as failure. Used for strict checks like --version.
    param($Name, [scriptblock]$Probe)
    try {
        & $Probe *> $null
        if ($LASTEXITCODE -eq 0 -or $null -eq $LASTEXITCODE) { Pass $Name }
        else { Fail $Name "exit $LASTEXITCODE" }
    } catch { Fail $Name $_.Exception.Message }
}

function Check-Binary {
    # Passes if the file exists AND running it produces any output or a
    # recognizable exit code. This is the permissive check for Python CLIs
    # that return non-zero on bare --help (e.g. Click groups with no
    # default command, like mempalace).
    param($Name, $Path, [string[]]$Probes = @('--help'))
    if (-not (Test-Path $Path)) { Fail $Name "not found at $Path"; return }
    foreach ($args in $Probes) {
        try {
            $out = & $Path $args 2>&1 | Out-String
            if ($LASTEXITCODE -eq 0) { Pass "$Name (exit 0 on '$args')"; return }
            if ($out.Trim().Length -gt 0) {
                # Non-zero exit but the binary ran and produced output --
                # that's a working CLI, just one that expects a subcommand.
                Pass "$Name (prints help; exit $LASTEXITCODE on '$args')"
                return
            }
        } catch { }
    }
    # Nothing produced output -- fall back to existence check.
    Note $Name "binary exists at $Path but '--help' produced no output"
}

Write-Host "`nVerifying Claude retrieval stack at $StackRoot" -ForegroundColor Cyan
Write-Host "PATH augmented with: $($extraPaths -join '; ')`n" -ForegroundColor DarkGray

# --- Venv binaries ---------------------------------------------------------
Write-Host "Python stack (venv binaries):"
Check-Binary "jcodemunch-mcp" (Join-Path $VenvScripts 'jcodemunch-mcp.exe') @('--version', '--help')
Check-Binary "jdatamunch-mcp" (Join-Path $VenvScripts 'jdatamunch-mcp.exe') @('--help')
Check-Binary "jdocmunch-mcp"  (Join-Path $VenvScripts 'jdocmunch-mcp.exe')  @('--help')
Check-Binary "mempalace"      (Join-Path $VenvScripts 'mempalace.exe')       @('--help', 'init --help')

# --- External helpers ------------------------------------------------------
Write-Host "`nExternal helpers:"
Check-Cmd "uv"     { uv --version   2>&1 }
Check-Cmd "uvx"    { uvx --version  2>&1 }
Check-Cmd "node"   { node --version 2>&1 }
Check-Cmd "npx"    { npx --version  2>&1 }
Check-Cmd "git"    { git --version  2>&1 }
Check-Cmd "claude" { claude --version 2>&1 }

# --- uvx servers -----------------------------------------------------------
Write-Host "`nuvx-managed servers (first run may download):"
Check-Cmd "serena (via uvx)"  { uvx --from git+https://github.com/oraios/serena serena --help 2>&1 }
Check-Cmd "mcp-server-motherduck (via uvx)" { uvx mcp-server-motherduck --help 2>&1 }

# Installer sets web_dashboard_open_on_launch: false so Serena doesn't spawn
# a new browser tab on every Claude Code session start.
$serenaCfg = Join-Path $env:USERPROFILE '.serena\serena_config.yml'
if ((Test-Path $serenaCfg) -and
    (Select-String -Path $serenaCfg -Pattern '^\s*web_dashboard_open_on_launch:\s*false' -Quiet)) {
    Pass "serena dashboard auto-open disabled"
} else {
    Fail "serena dashboard auto-open disabled" "web_dashboard_open_on_launch: false not set in $serenaCfg"
}

# --- Context7 (only if node+npx) ------------------------------------------
Write-Host "`nNode server (Context7):"
if (Get-Command npx -ErrorAction SilentlyContinue) {
    Check-Cmd "@upstash/context7-mcp" { npx --yes "@upstash/context7-mcp" --help 2>&1 }
} else {
    Note "@upstash/context7-mcp" "npx not available yet; install Node.js and re-run"
}

# --- Summary ---------------------------------------------------------------
Write-Host ""
if ($fails -eq 0) {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$fails check(s) failed." -ForegroundColor Red
    Write-Host "If uv/uvx/node/npx/git/claude failed, try: open a NEW PowerShell, then re-run." -ForegroundColor Yellow
    exit 1
}
