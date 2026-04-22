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
# --inexact: don't remove extraneous packages (e.g. langfuse installed by
# install-langfuse.ps1). Without this, re-running install.ps1 after
# install-langfuse.ps1 silently deletes the Langfuse SDK and breaks the
# Stop hook.
uv sync --inexact
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

# --- 3b. Configure Serena: disable dashboard browser auto-open --------------
# Serena's default is to open a new browser tab every time its MCP server
# starts -- once per Claude Code session. With multiple sessions or orphan
# Serena processes, tabs pile up. The dashboard stays reachable manually at
# http://localhost:24282/dashboard/ (port increments if multiple instances).
Write-Step "Configuring Serena: disable dashboard browser auto-open"
$SerenaCfg = Join-Path $env:USERPROFILE '.serena\serena_config.yml'
$SerenaDir = Split-Path $SerenaCfg -Parent
if (-not (Test-Path $SerenaDir)) {
    New-Item -ItemType Directory -Path $SerenaDir -Force | Out-Null
}

# Nudge Serena to write its default config if it hasn't yet. `--help` exits
# before config load, so briefly start the MCP server as a background job
# and reap it after 10 s -- long enough for config creation, short enough
# to not block the installer.
if (-not (Test-Path $SerenaCfg)) {
    $job = Start-Job -ScriptBlock {
        & uvx --from git+https://github.com/oraios/serena serena start-mcp-server --context ide-assistant *>&1 | Out-Null
    }
    Wait-Job  $job -Timeout 10 | Out-Null
    Stop-Job  $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}

if (Test-Path $SerenaCfg) {
    $content = Get-Content $SerenaCfg -Raw
    if ($content -match '(?m)^\s*web_dashboard_open_on_launch:') {
        $content = [regex]::Replace($content, '(?m)^(\s*web_dashboard_open_on_launch:).*$', '$1 false')
        Set-Content -Path $SerenaCfg -Value $content -NoNewline
    } else {
        Add-Content -Path $SerenaCfg -Value "`nweb_dashboard_open_on_launch: false"
    }
    Write-OK "Serena dashboard auto-open disabled"
} else {
    $stub = @'
# Managed by Uncle J's Refinery install.ps1.
# Prevents Serena from auto-opening a browser tab on each MCP session
# start. Dashboard still reachable at http://localhost:24282/dashboard/
# (port increments if multiple Serena instances run concurrently).
web_dashboard_open_on_launch: false
'@
    Set-Content -Path $SerenaCfg -Value $stub
    Write-OK "Serena config stub written"
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

# --- 4b. Patch hook commands to use the full venv-binary path ---------------
# `jcodemunch-mcp init --hooks` writes bare `jcodemunch-mcp <subcommand>`
# into ~/.claude/settings.json. Those only resolve if the venv is on PATH,
# which it usually isn't — so every Claude Code tool call prints
# "command not found" for the enforcement hooks. Rewrite to the full
# path so hooks actually fire.
$patchScript = Join-Path $StackRoot 'patch-jcodemunch-hook-paths.py'
if (Test-Path $patchScript) {
    Write-Step "Patching jcodemunch-mcp hook commands to use full binary path"
    try {
        & python $patchScript
        Write-OK "hook paths patched"
    } catch {
        Write-Warn2 "hook path patch failed: $_  (hooks will print 'command not found' at runtime; re-run .\\patch-jcodemunch-hook-paths.py manually)"
    }
} else {
    Write-Warn2 "patch-jcodemunch-hook-paths.py missing from stack root; hook commands may fail with 'command not found'."
}

# --- 4c. Render mcp-clients/*.json from *.json.tmpl --------------------------
# The committed templates use {{STACK_VENV_BIN}} and {{EXE}} placeholders so
# the same files work on Linux and Windows. Install-time rendering produces
# platform-specific .json files (gitignored) that users can paste into
# their MCP client configs.
Write-Step "Rendering mcp-clients/*.json from templates"
$McpDir = Join-Path $StackRoot 'mcp-clients'
# JSON parsers accept forward slashes in Windows paths; using them here keeps
# sed-style substitution simple and avoids JSON escaping of backslashes.
$VenvBinFwd = $VenvScripts -replace '\\','/'
$tmpls = Get-ChildItem -Path $McpDir -Filter '*.json.tmpl' -ErrorAction SilentlyContinue
if ($tmpls) {
    foreach ($t in $tmpls) {
        $out = $t.FullName -replace '\.tmpl$',''
        (Get-Content $t.FullName -Raw) `
            -replace '\{\{STACK_VENV_BIN\}\}', $VenvBinFwd `
            -replace '\{\{EXE\}\}', '.exe' `
            | Set-Content -Path $out -Encoding UTF8
        Write-OK "rendered $([System.IO.Path]::GetFileName($out))"
    }
} else {
    Write-Warn2 "no *.json.tmpl files in $McpDir; skipping render"
}

# --- 5. Optional auto-registration with Claude Code --------------------------
# `claude mcp add -s user <name>` silently skips when the name is already
# registered (e.g. as `uvx jcodemunch-mcp` after `jcodemunch-mcp init`).
# `jcodemunch-mcp init` writes at *local* scope, which wins over user scope,
# so we must clear all three scopes before re-adding at user scope.
function Invoke-McpAdd {
    param([string]$Name, [string[]]$AddArgs)
    & claude mcp remove -s local   $Name 2>$null | Out-Null
    & claude mcp remove -s project $Name 2>$null | Out-Null
    & claude mcp remove -s user    $Name 2>$null | Out-Null
    & claude mcp add -s user $Name @AddArgs
}
if ($AutoRegister -and -not $skipClaudeCli) {
    Write-Step "Registering MCP servers with Claude Code (user scope)"
    Invoke-McpAdd jcodemunch @($exe.jcodemunch)
    Invoke-McpAdd jdatamunch @($exe.jdatamunch)
    Invoke-McpAdd jdocmunch  @($exe.jdocmunch)
    Invoke-McpAdd mempalace  @('--', (Join-Path $VenvScripts 'python.exe'), '-m', 'mempalace.mcp_server')
    Invoke-McpAdd serena     @('--', 'uvx', '--from', 'git+https://github.com/oraios/serena', 'serena', 'start-mcp-server', '--context', 'ide-assistant')
    if (-not $skipContext7) {
        Invoke-McpAdd context7 @('--', 'npx', '-y', '@upstash/context7-mcp')
    }
    if (-not $SkipOptional) {
        Invoke-McpAdd duckdb @('--', 'uvx', 'mcp-server-motherduck', '--db-path', ':memory:', '--read-write', '--allow-switch-databases')
    }
    Write-OK "Registered with Claude Code. Verify with:  claude mcp list"
}

# --- 5b. MCP server startup timeout ------------------------------------------
# Claude Code honors MCP_TIMEOUT from its settings.json env block. Set it
# here so first-run cold starts (uvx fetches, npx resolves) don't race the
# default 30s timeout — especially relevant for Serena and MotherDuck which
# can take 40-50s on their first invocation.
Write-Step "Setting MCP_TIMEOUT in settings.json"
$claudeDir = if ($env:CLAUDE_HOME) { $env:CLAUDE_HOME } else { Join-Path $env:USERPROFILE ".claude" }
if (-not (Test-Path $claudeDir)) { New-Item -Path $claudeDir -ItemType Directory | Out-Null }
$settingsPath = Join-Path $claudeDir "settings.json"
if (-not (Test-Path $settingsPath)) { '{}' | Set-Content -Path $settingsPath -Encoding UTF8 }
$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
if (-not $settings.env) { $settings | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{}) -Force }
if ($settings.env.MCP_TIMEOUT -ne "60000") {
    if ($settings.env.PSObject.Properties['MCP_TIMEOUT']) {
        $settings.env.MCP_TIMEOUT = "60000"
    } else {
        $settings.env | Add-Member -NotePropertyName MCP_TIMEOUT -NotePropertyValue "60000" -Force
    }
    $settings | ConvertTo-Json -Depth 99 | Set-Content -Path $settingsPath -Encoding UTF8
    Write-OK "MCP_TIMEOUT=60000 set in settings.json env block"
} else {
    Write-OK "MCP_TIMEOUT already 60000 in settings.json env block"
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

# --- 7. Optional features -----------------------------------------------------
Write-Step "Optional features"
. "$StackRoot\lib\feature-helpers.ps1"
Write-Host ""
if (Prompt-YesNo "Enable automated stack update alerts (Telegram)?") {
    & "$StackRoot\features\stack-alerts\install.ps1"
}
