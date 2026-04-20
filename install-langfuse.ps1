<#
.SYNOPSIS
    Install self-hosted Langfuse (LLM observability) wired to Claude Code
    via the doneyli template.

.DESCRIPTION
    Langfuse captures every Claude Code session -- user messages, tool
    calls, costs, latencies -- as OpenTelemetry traces viewable in a
    local web UI at http://localhost:3050.

    This installer:
      1. Checks Docker Desktop is available (offers winget install if not).
      2. Clones doneyli/claude-code-langfuse-template into _stack_setup/.
      3. Generates random API keys via the template's generate-env.sh.
      4. Starts the stack: `docker compose up -d`.
      5. Runs install-hook.sh which adds a Stop hook to
         ~/.claude/settings.json with the generated keys.
      6. Prints the web UI URL.

    The Stop hook fires after each assistant response completes, shipping
    the conversation to Langfuse. Zero impact on normal usage -- the hook
    is async.

.PARAMETER SkipDockerInstall
    Don't try to install Docker Desktop even if missing. Use when you
    have Docker via Rancher, Podman Desktop, or another provider.

.PARAMETER NoStart
    Clone + generate env but don't actually start containers or install
    hook. For dry inspection.

.NOTES
    Ports used:
      3050 - Langfuse web UI
      5433 - Postgres
      8124 - ClickHouse
      6379 - Redis
      9090 - MinIO (object storage)
    If any of these are occupied, edit docker-compose.yml in the
    cloned template before starting.

    Stop the stack:  docker compose -f _stack_setup\claude-code-langfuse-template\docker-compose.yml down
    Update the stack: git -C _stack_setup\claude-code-langfuse-template pull && docker compose up -d
#>

[CmdletBinding()]
param(
    [switch]$SkipDockerInstall,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$StackRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$TemplateDir = Join-Path $StackRoot 'claude-code-langfuse-template'
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

# --- 1. Docker -------------------------------------------------------------
Write-Step "Checking Docker"
$dockerOk = $false
if (Has-Cmd docker) {
    try {
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
    } catch { }
}
if (-not $dockerOk) {
    if ($SkipDockerInstall) {
        Write-Warn2 "-SkipDockerInstall set and Docker not running. Start it, then re-run."
        exit 1
    }
    if (-not (Has-Cmd docker)) {
        Write-Step "Installing Docker Desktop via winget (Docker.DockerDesktop)"
        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "winget exited $LASTEXITCODE" }
        Write-Warn2 "Docker Desktop installed but must be started manually at least once (sets up WSL2 backend)."
        Write-Warn2 "Start Docker Desktop, wait for the whale icon in the tray to go solid, then re-run this script."
        exit 0
    } else {
        Write-Warn2 "docker command exists but `docker info` failed. Docker Desktop isn't running."
        Write-Warn2 "Start Docker Desktop (system tray whale icon), wait for it to go solid, then re-run."
        exit 1
    }
}
Write-OK "Docker is running"

# Verify docker compose v2 is available (required by the template)
docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "`docker compose` (v2) not available. The template requires compose v2, not docker-compose v1."
    exit 1
}

# --- 2. Git Bash for the template's shell scripts -------------------------
$bashPath = $null
foreach ($p in @(
    'C:\Program Files\Git\bin\bash.exe',
    'C:\Program Files (x86)\Git\bin\bash.exe'
)) {
    if (Test-Path $p) { $bashPath = $p; break }
}
if (-not $bashPath -and (Has-Cmd bash)) { $bashPath = (Get-Command bash).Source }
if (-not $bashPath) { throw "Git Bash not found. Run prerequisites.ps1 first." }
Write-OK "Git Bash: $bashPath"

# --- 3. Clone (or pull) the template --------------------------------------
if (-not (Test-Path $TemplateDir)) {
    Write-Step "Cloning doneyli/claude-code-langfuse-template"
    git clone https://github.com/doneyli/claude-code-langfuse-template.git $TemplateDir
} else {
    Write-Step "claude-code-langfuse-template already cloned; pulling latest"
    git -C $TemplateDir pull --ff-only
}

# --- 4. Generate env vars (random API keys) -------------------------------
$msysTemplate = ($TemplateDir -replace '\\','/') -replace '^C:','/c'

Write-Step "Preparing .env"
& $bashPath -c "cd '$msysTemplate' && cp -n .env.example .env && ./scripts/generate-env.sh"
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "generate-env.sh exited $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-OK ".env generated"

if ($NoStart) {
    Write-Warn2 "-NoStart set; skipping docker compose + hook install"
    Write-Host "To finish later, run:"
    Write-Host "  cd $TemplateDir; docker compose up -d; bash ./scripts/install-hook.sh" -ForegroundColor Yellow
    exit 0
}

# --- 5. Start the stack ----------------------------------------------------
Write-Step "Starting Langfuse stack (docker compose up -d)"
Push-Location $TemplateDir
try {
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit $LASTEXITCODE" }
} finally {
    Pop-Location
}
Write-OK "Containers started"

# Wait for the web UI to respond
Write-Step "Waiting for Langfuse web UI (up to 90s)"
$started = $false
for ($i = 0; $i -lt 45; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri 'http://localhost:3050/api/public/health' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $started = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if ($started) { Write-OK "Web UI reachable at http://localhost:3050" }
else          { Write-Warn2 "Web UI didn't answer within 90s. Check `docker compose logs` -- proceeding anyway." }

# --- 6. Backup settings.json before hook install --------------------------
if (Test-Path (Join-Path $ClaudeDir 'settings.json')) {
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $src = Join-Path $ClaudeDir 'settings.json'
    $dst = "$src.backup.$ts.pre-langfuse"
    Copy-Item -Path $src -Destination $dst
    Write-OK "backed up settings.json -> $(Split-Path $dst -Leaf)"
}

# --- 7. Install the Stop hook ---------------------------------------------
Write-Step "Running install-hook.sh to wire Stop hook into ~/.claude/settings.json"
& $bashPath -c "cd '$msysTemplate' && ./scripts/install-hook.sh"
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "install-hook.sh exited $LASTEXITCODE -- inspect settings.json manually"
    exit $LASTEXITCODE
}
Write-OK "Stop hook installed"

# --- 8. Summary -----------------------------------------------------------
Write-Step "Done"
Write-Host @"

Langfuse observability is live.

Web UI:       http://localhost:3050
Credentials:  see $TemplateDir\.env (LANGFUSE_INIT_USER_EMAIL / _PASSWORD)

Every Claude Code session will now stream its trace to Langfuse:
  * user messages
  * tool calls (jcodemunch, serena, etc.) with latency
  * token counts and estimated cost
  * errors

Start a NEW Claude Code session so the Stop hook picks up.

Useful commands:
  docker compose -f $TemplateDir\docker-compose.yml ps
  docker compose -f $TemplateDir\docker-compose.yml logs -f
  docker compose -f $TemplateDir\docker-compose.yml down          # stop
  docker compose -f $TemplateDir\docker-compose.yml down --volumes # stop + wipe traces

"@ -ForegroundColor White
