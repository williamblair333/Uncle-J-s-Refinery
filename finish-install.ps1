<#
.SYNOPSIS
    Finishes the stack install after prerequisites (git / node / claude CLI)
    are in place.

.DESCRIPTION
    Should be run in a fresh PowerShell window after prerequisites.ps1.
    Does three things:
      1. Warm-caches Serena via uvx (needs git, which install.ps1 couldn't
         use because git was missing at the time).
      2. Verifies Context7 is reachable via npx.
      3. Auto-registers all seven MCP servers with Claude Code at user
         scope (`claude mcp add -s user ...`).

    Idempotent. Safe to re-run.
#>

[CmdletBinding()]
param(
    [switch]$SkipAutoRegister,
    [switch]$SkipContext7
)

$ErrorActionPreference = 'Continue'
$StackRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvScripts = Join-Path $StackRoot ".venv\Scripts"

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "    !!  $m" -ForegroundColor Yellow }
function Has-Cmd    { param($n) [bool](Get-Command $n -ErrorAction SilentlyContinue) }

# --- PATH self-heal --------------------------------------------------------
# STEP A: Refresh PATH from the registry (machine + user). This is what a
# brand-new PowerShell would see. Fixes "I just ran prerequisites.ps1 and
# this shell doesn't see git/node/claude yet."
try {
    $machinePath = [System.Environment]::GetEnvironmentVariable('Path','Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$machinePath;$userPath"
} catch { }

# STEP B: Pre-pend known install locations as a safety net.
$extraPaths = @(
    "$env:USERPROFILE\.local\bin",
    "$env:ProgramFiles\Git\cmd",
    "$env:ProgramFiles\nodejs",
    "$env:APPDATA\npm",
    "$env:LOCALAPPDATA\AnthropicClaude",
    "$env:LOCALAPPDATA\Programs\claude",
    "$env:LOCALAPPDATA\Programs\Anthropic\Claude Code",
    "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
    "$env:LOCALAPPDATA\Microsoft\WinGet\Packages"
) | Where-Object { Test-Path $_ }

foreach ($p in $extraPaths) {
    if (-not ($env:Path -split ';' -contains $p)) {
        $env:Path = "$p;$env:Path"
    }
}

# --- 1. Prereq check -------------------------------------------------------
Write-Step "Re-checking prerequisites"
$missing = @()
foreach ($cmd in 'uv','uvx','git') {
    if (Has-Cmd $cmd) { Write-OK "$cmd available" } else { $missing += $cmd }
}
foreach ($cmd in 'node','npx') {
    if (Has-Cmd $cmd) { Write-OK "$cmd available" } else {
        if ($SkipContext7) { Write-Warn2 "$cmd missing (Context7 skipped)" }
        else { $missing += $cmd }
    }
}
foreach ($cmd in 'claude') {
    if (Has-Cmd $cmd) { Write-OK "$cmd available" } else {
        if ($SkipAutoRegister) { Write-Warn2 "$cmd missing (auto-register skipped)" }
        else { $missing += $cmd }
    }
}

if ($missing.Count -gt 0) {
    Write-Warn2 "Missing: $($missing -join ', ')"
    Write-Warn2 "Run .\prerequisites.ps1 first, OPEN A NEW POWERSHELL, then re-run this script."
    Write-Warn2 "Or pass -SkipAutoRegister / -SkipContext7 to skip the pieces that need them."
    exit 1
}

# --- 2. Warm-cache Serena (needs git) -------------------------------------
Write-Step "Warm-caching Serena via uvx (first run clones from GitHub)"
try {
    uvx --from git+https://github.com/oraios/serena serena --help *> $null
    if ($LASTEXITCODE -eq 0) { Write-OK "Serena cached" }
    else { Write-Warn2 "Serena warm-cache exit $LASTEXITCODE (uvx will retry when MCP invokes it)" }
} catch {
    Write-Warn2 "Serena warm-cache threw: $_"
}

# --- 3. Test Context7 resolves ---------------------------------------------
if (-not $SkipContext7 -and (Has-Cmd 'npx')) {
    Write-Step "Testing Context7 (npx @upstash/context7-mcp)"
    try {
        npx --yes "@upstash/context7-mcp" --help *> $null
        if ($LASTEXITCODE -eq 0) { Write-OK "Context7 resolvable" }
        else { Write-Warn2 "Context7 probe exit $LASTEXITCODE (first call downloads the package)" }
    } catch {
        Write-Warn2 "Context7 probe threw: $_"
    }
}

# --- 4. Auto-register with Claude Code CLI --------------------------------
if (-not $SkipAutoRegister -and (Has-Cmd 'claude')) {
    Write-Step "Registering MCP servers with Claude Code (user scope)"

    $servers = @(
        @{ Name='jcodemunch'; Args=@('mcp','add','-s','user','jcodemunch', (Join-Path $VenvScripts 'jcodemunch-mcp.exe')) }
        @{ Name='jdatamunch'; Args=@('mcp','add','-s','user','jdatamunch', (Join-Path $VenvScripts 'jdatamunch-mcp.exe')) }
        @{ Name='jdocmunch';  Args=@('mcp','add','-s','user','jdocmunch',  (Join-Path $VenvScripts 'jdocmunch-mcp.exe'))  }
        @{ Name='mempalace';  Args=@('mcp','add','-s','user','mempalace','--', (Join-Path $VenvScripts 'python.exe'), '-m', 'mempalace.mcp_server') }
        @{ Name='serena';     Args=@('mcp','add','-s','user','serena','--','uvx','--from','git+https://github.com/oraios/serena','serena','start-mcp-server','--context','ide-assistant') }
        @{ Name='duckdb';     Args=@('mcp','add','-s','user','duckdb','--','uvx','mcp-server-motherduck','--db-path',':memory:','--read-write','--allow-switch-databases') }
    )
    if (-not $SkipContext7 -and (Has-Cmd 'npx')) {
        $servers += @{ Name='context7'; Args=@('mcp','add','-s','user','context7','--','npx','-y','@upstash/context7-mcp') }
    }

    foreach ($s in $servers) {
        try {
            & claude @($s.Args)
            if ($LASTEXITCODE -eq 0) { Write-OK "registered: $($s.Name)" }
            else { Write-Warn2 "claude mcp add for $($s.Name) exited $LASTEXITCODE (already registered? run 'claude mcp list')" }
        } catch {
            Write-Warn2 "claude mcp add for $($s.Name) threw: $_"
        }
    }

    Write-Step "Listing registered MCP servers"
    & claude mcp list
}

Write-Step "Done"
Write-Host @"

Next:
  .\verify.ps1                                       # should now report all PASS
  .\.venv\Scripts\mempalace.exe init <project-path>  # bootstrap memory per project

If verify still has FAILs, open a NEW PowerShell window (PATH refresh) and run
verify.ps1 again before debugging -- shell staleness is the #1 cause of false
FAILs on this stack.

"@ -ForegroundColor White
