<#
.SYNOPSIS
    One-shot installer for the Claude retrieval stack on Windows.

.DESCRIPTION
    Installs jCodeMunch, jDataMunch, jDocMunch, and MemPalace into an isolated
    uv-managed Python virtual environment, plus checks that the helper tooling
    (uvx, npx, claude) for Serena, Context7, and MotherDuck/DuckDB is available.
    Prints next-step commands to register everything with Claude Desktop / Claude
    Code.

.NOTES
    Run from this folder:  powershell -ExecutionPolicy Bypass -File .\install.ps1
    Re-runs are idempotent.
#>

[CmdletBinding()]
param(
    [switch]$SkipOptional,
    [switch]$AutoRegister    # if set, attempts `claude mcp add ...` automatically
)

$ErrorActionPreference = 'Stop'
$StackRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $StackRoot

function Write-Step  { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK    { param($m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "    !!  $m" -ForegroundColor Yellow }
function Has-Cmd     { param($n) [bool](Get-Command $n -ErrorAction SilentlyContinue) }

# --- 1. Prereqs --------------------------------------------------------------
Write-Step "Checking prerequisites"

if (-not (Has-Cmd 'python')) {
    throw "Python 3.11+ not found on PATH. Install from https://python.org and re-run."
}
$pyVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
Write-OK "python $pyVersion"

if (-not (Has-Cmd 'uv')) {
    Write-Step "Installing uv (fast Python package manager)"
    # Official installer
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    # uv installs to %USERPROFILE%\.local\bin -- refresh PATH in-process
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Has-Cmd 'uv')) { throw "uv install succeeded but 'uv' not on PATH. Open a new shell and re-run." }
}
Write-OK "uv $((uv --version) -replace 'uv ','')"

if (-not (Has-Cmd 'node')) {
    Write-Warn2 "Node.js not found. Context7 (third-party library docs) will be skipped."
    Write-Warn2 "Install Node 18+ from https://nodejs.org then re-run to enable Context7."
    $skipContext7 = $true
} else {
    Write-OK "node $((node --version))"
    $skipContext7 = $false
}

if (-not (Has-Cmd 'claude')) {
    Write-Warn2 "Claude Code CLI ('claude') not found. Auto-registration will be skipped."
    Write-Warn2 "Install from https://github.com/anthropics/claude-code if you want AutoRegister."
    $skipClaudeCli = $true
} else {
    Write-OK "claude CLI found"
    $skipClaudeCli = $false
}

# --- 2. Create the venv and install the Python stack -------------------------
Write-Step "Creating .venv with uv"
if (-not (Test-Path ".venv")) {
    uv venv --python "3.11"
}
Write-OK ".venv ready at $StackRoot\.venv"

Write-Step "Installing Python stack (jCodeMunch, jDataMunch, jDocMunch, MemPalace)"
# uv sync reads pyproject.toml and installs exactly what's declared.
uv sync
Write-OK "Python stack installed"

# Resolve full paths of the installed executables so MCP configs can point
# at them unambiguously. The venv Scripts folder is where pip installs
# console_scripts entry points on Windows.
$VenvScripts = Join-Path $StackRoot ".venv\Scripts"
$exe = @{
    jcodemunch = Join-Path $VenvScripts 'jcodemunch-mcp.exe'
    jdatamunch = Join-Path $VenvScripts 'jdatamunch-mcp.exe'
    jdocmunch  = Join-Path $VenvScripts 'jdocmunch-mcp.exe'
    mempalace  = Join-Path $VenvScripts 'mempalace.exe'
}
foreach ($k in $exe.Keys) {
    if (Test-Path $exe[$k]) { Write-OK "$k -> $($exe[$k])" }
    else { Write-Warn2 "$k missing at $($exe[$k])" }
}

# --- 3. Warm-cache Serena and MotherDuck via uvx -----------------------------
Write-Step "Warm-caching Serena (uvx pulls it on first use; doing it now)"
try {
    uvx --from git+https://github.com/oraios/serena serena --help | Out-Null
    Write-OK "Serena cached"
} catch {
    Write-Warn2 "Serena warm-cache failed: $_"
    Write-Warn2 "This is non-fatal -- uvx will retry when MCP actually invokes it."
}

if (-not $SkipOptional) {
    Write-Step "Warm-caching mcp-server-motherduck"
    try {
        uvx mcp-server-motherduck --help | Out-Null
        Write-OK "mcp-server-motherduck cached"
    } catch {
        Write-Warn2 "mcp-server-motherduck warm-cache failed: $_"
    }
}

# --- 4. Configure jCodeMunch's prompt policy + hooks -------------------------
# `jcodemunch-mcp init` writes CLAUDE.md prompt policy + optional PreToolUse /
# PostToolUse / PreCompact hooks. Our CLAUDE.md replaces the generic one it
# would write, but hooks are the real accuracy lever so we install them.
Write-Step "Running jcodemunch-mcp init --yes --hooks --audit (non-destructive)"
try {
    & $exe.jcodemunch init --yes --hooks --audit 2>&1 | Tee-Object -FilePath "$StackRoot\.install-jcm-init.log"
    Write-OK "jcodemunch init complete"
} catch {
    Write-Warn2 "jcodemunch init failed: $_  (see .install-jcm-init.log)"
}

# --- 5. Optional auto-registration with Claude Code --------------------------
if ($AutoRegister -and -not $skipClaudeCli) {
    Write-Step "Registering MCP servers with Claude Code (user scope)"
    & claude mcp add -s user jcodemunch $exe.jcodemunch
    & claude mcp add -s user jdatamunch $exe.jdatamunch
    & claude mcp add -s user jdocmunch  $exe.jdocmunch
    & claude mcp add -s user mempalace -- (Join-Path $VenvScripts 'python.exe') -m mempalace.mcp_server
    & claude mcp add -s user serena -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant
    if (-not $skipContext7) {
        & claude mcp add -s user context7 -- npx -y "@upstash/context7-mcp"
    }
    if (-not $SkipOptional) {
        & claude mcp add -s user duckdb -- uvx mcp-server-motherduck --db-path :memory: --read-write --allow-switch-databases
    }
    Write-OK "Registered with Claude Code. Verify with:  claude mcp list"
}

# --- 6. Next-step guidance ---------------------------------------------------
Write-Step "Next steps"
Write-Host @"

Installed. What to do now:

1. Paste the MCP config fragment into your client:
     Claude Desktop  -> mcp-clients\claude-desktop-config-fragment.json
     Claude Code     -> mcp-clients\claude-code-mcp.json  (or re-run with -AutoRegister)
     Cursor          -> mcp-clients\cursor-mcp.json
     Windsurf        -> mcp-clients\windsurf-mcp.json

2. Install CLAUDE.md (routing policy) globally OR per-project:
     Global : copy CLAUDE.md  %USERPROFILE%\.claude\CLAUDE.md
     Project: copy CLAUDE.md into the repo root you're working in

3. Bootstrap MemPalace for a project (one-time per project):
     .\.venv\Scripts\mempalace.exe init C:\path\to\your\project
     .\.venv\Scripts\mempalace.exe mine C:\path\to\your\project
     .\.venv\Scripts\mempalace.exe mine $env:USERPROFILE\.claude\projects\ --mode convos

4. Sanity-check:
     .\verify.ps1

5. Get free Context7 API key (optional, higher rate limits):
     https://context7.com/dashboard   -- put it in %USERPROFILE%\.claude\.env as
     CONTEXT7_API_KEY=...

"@ -ForegroundColor White
