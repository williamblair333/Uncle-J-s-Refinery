<#
.SYNOPSIS
    Runtime invariants check for Uncle J's Refinery (Windows parity
    with healthcheck.sh).

.DESCRIPTION
    Complements verify.ps1 (install-time binary checks) by verifying
    the stack is actually wired up and responding. Catches the silent
    regressions that install-time checks miss:
      - jcodemunch registered at local scope (masks the venv path)
      - langfuse wiped from .venv by a uv sync (Stop hook dies silently)
      - docker stack crashed overnight
      - MCP_TIMEOUT or Langfuse env reset
      - secrets committed to the working tree

.PARAMETER Quick
    Default. <~6s. Safe for SessionStart hook.

.PARAMETER Full
    Runs verify.ps1 + end-to-end smoke (nested claude -p + trace API).

.OUTPUTS
    Exit 0 if all checks pass, 1 if any fail.
    Final stdout line is machine-parseable:
      HEALTHCHECK: ok
      HEALTHCHECK: fail (<count>) -- <first failing check>
#>

[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$Full
)

$ErrorActionPreference = 'Continue'  # a failed check must not abort the rest

if (-not $Quick -and -not $Full) { $Quick = $true }

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Mode = if ($Full) { 'full' } else { 'quick' }

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Bad  { param($m) Write-Host "    X   $m" -ForegroundColor Red }
function Write-Hint { param($m) Write-Host "        fix: $m" -ForegroundColor Yellow }

$script:ChecksFailed = 0
$script:FirstFail = ''
function Record-Fail {
    param($name)
    $script:ChecksFailed++
    if (-not $script:FirstFail) { $script:FirstFail = $name }
}

function Get-SettingsEnv {
    param($Key)
    $settings = Join-Path $HOME '.claude/settings.json'
    try {
        $d = Get-Content $settings -Raw | ConvertFrom-Json
        return $d.env.$Key
    } catch { return '' }
}

# ----- 1. verify.ps1 (full mode only) ---------------------------------------
function Check-Verify {
    Write-Step "1. verify.ps1 (install-time binaries)"
    $verify = Join-Path $RepoRoot 'verify.ps1'
    & pwsh -NoProfile -File $verify *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "verify.ps1 all PASS"
    } else {
        Write-Bad "verify.ps1 reported failures"
        Write-Hint "run: $verify"
        Record-Fail 'verify.ps1'
    }
}

# ----- 2. all 7 stack MCP servers connected ---------------------------------
function Check-McpConnected {
    Write-Step "2. claude mcp list -- 7 stack servers Connected"
    $output = & claude mcp list 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "claude mcp list failed"
        Write-Hint "run: $RepoRoot\install.ps1 -AutoRegister"
        Record-Fail 'mcp-list'
        return
    }
    $missing = @()
    foreach ($name in @('duckdb','jcodemunch','jdatamunch','jdocmunch','mempalace','serena','context7')) {
        if ($output -notmatch "(?m)^${name}: .*Connected") { $missing += $name }
    }
    if ($missing.Count -eq 0) {
        Write-OK "all 7 stack servers Connected"
    } else {
        Write-Bad ("not Connected: " + ($missing -join ' '))
        Write-Hint "run: $RepoRoot\install.ps1 -AutoRegister"
        Record-Fail "mcp-servers-down($($missing[0]))"
    }
}

# ----- 3. jcodemunch at venv path (NOT uvx) --------------------------------
function Check-JcodemunchPath {
    Write-Step "3. jcodemunch running from stack venv (not uvx)"
    $expected = Join-Path $RepoRoot '.venv\Scripts\jcodemunch-mcp.exe'
    $output = & claude mcp get jcodemunch 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "claude mcp get jcodemunch failed"
        Record-Fail 'jcodemunch-get'
        return
    }
    # Windows venv scripts can resolve as either .exe or no-suffix — accept both
    if ($output -like "*$RepoRoot\.venv\Scripts\jcodemunch-mcp*") {
        Write-OK "jcodemunch -> $expected"
    } else {
        Write-Bad "jcodemunch not at venv path -- likely a stale local-scope registration"
        Write-Hint "run: claude mcp remove jcodemunch -s local ; claude mcp remove jcodemunch -s project"
        Record-Fail 'jcodemunch-wrong-scope'
    }
}

# ----- 4. MCP_TIMEOUT = 60000 ----------------------------------------------
function Check-McpTimeout {
    Write-Step "4. MCP_TIMEOUT=60000 in ~/.claude/settings.json"
    $actual = Get-SettingsEnv 'MCP_TIMEOUT'
    if ($actual -eq '60000') {
        Write-OK "MCP_TIMEOUT=60000"
    } else {
        Write-Bad "MCP_TIMEOUT=$actual (expected 60000)"
        Write-Hint "re-run: $RepoRoot\install.ps1"
        Record-Fail 'mcp-timeout'
    }
}

# ----- 5. Langfuse compose health ------------------------------------------
function Check-LangfuseCompose {
    Write-Step "5. Langfuse docker compose: 6 up, 4 healthy"
    $compose = Join-Path $RepoRoot 'claude-code-langfuse-template\docker-compose.yml'
    if (-not (Test-Path $compose)) {
        Write-Bad "compose file missing: $compose"
        Write-Hint "run: $RepoRoot\install-langfuse.ps1"
        Record-Fail 'langfuse-compose-missing'
        return
    }
    $raw = & docker compose -f $compose ps --format json 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "docker compose ps failed"
        Write-Hint "check: docker info  # is Docker Desktop running?"
        Record-Fail 'docker-down'
        return
    }
    # compose v2 emits either ndjson (one object per line) or a JSON array.
    $services = @()
    $trim = $raw.Trim()
    if ($trim.StartsWith('[')) {
        $services = $trim | ConvertFrom-Json
    } else {
        $services = $trim -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }
    }
    $total   = $services.Count
    $running = ($services | Where-Object { $_.State -eq 'running' }).Count
    $healthy = ($services | Where-Object { $_.Health -eq 'healthy' }).Count
    if ($total -ge 6 -and $running -ge 6 -and $healthy -ge 4) {
        Write-OK "$running running, $healthy healthy"
    } else {
        Write-Bad "compose state: total=$total running=$running healthy=$healthy (want >=6 running, >=4 healthy)"
        Write-Hint "run: docker compose -f $compose up -d"
        Record-Fail 'langfuse-unhealthy'
    }
}

# ----- 6. Langfuse /api/public/health --------------------------------------
function Check-LangfuseApi {
    Write-Step "6. Langfuse API /api/public/health"
    try {
        $r = Invoke-RestMethod -Uri 'http://localhost:3050/api/public/health' -TimeoutSec 3
        if ($r.status -eq 'OK') {
            Write-OK "status=OK"
        } else {
            Write-Bad "health endpoint did not return status=OK"
            Record-Fail 'langfuse-api'
        }
    } catch {
        Write-Bad "health endpoint unreachable: $_"
        Write-Hint "run: docker compose -f $RepoRoot\claude-code-langfuse-template\docker-compose.yml logs --tail=50 langfuse-web"
        Record-Fail 'langfuse-api'
    }
}

# ----- 7. langfuse SDK importable from stack venv --------------------------
function Check-LangfuseSdk {
    Write-Step "7. langfuse SDK importable from stack venv"
    $py = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Write-Bad "stack venv python missing at $py"
        Write-Hint "run: $RepoRoot\install.ps1"
        Record-Fail 'venv-python-missing'
        return
    }
    & $py -c "from langfuse import Langfuse" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "from langfuse import Langfuse -> OK"
    } else {
        Write-Bad "langfuse not importable from $py -- Stop hook silently dies without this"
        Write-Hint "run: uv pip install --python `"$py`" --upgrade 'langfuse>=3.0,<4'"
        Record-Fail 'langfuse-sdk-missing'
    }
}

# ----- 8. no leaked secrets in tree ----------------------------------------
function Check-Secrets {
    Write-Step "8. working tree: no leaked secrets"
    Push-Location $RepoRoot
    try {
        $hits = & git grep -iE 'sk-lf-[a-f0-9]{16,}|PASSWORD=[a-zA-Z0-9]{8,}' 2>$null
        if (-not $hits) {
            Write-OK "no sk-lf-* or PASSWORD=... matches"
        } else {
            Write-Bad "secret-looking strings found in tracked files"
            $hits | Select-Object -First 3 | ForEach-Object { Write-Host "        $_" }
            Write-Hint "review the matches; add the file to .gitignore or redact"
            Record-Fail 'secrets'
        }
    } finally { Pop-Location }
}

# ===== full-mode extras =====================================================
function Check-SmokeHook {
    Write-Step "9. smoke: claude -p writes a new line to langfuse_hook.log"
    $log = Join-Path $HOME '.claude\state\langfuse_hook.log'
    $before = if (Test-Path $log) { (Get-Content $log | Measure-Object -Line).Lines } else { 0 }
    $null = & claude -p 'healthcheck-smoke' --dangerously-skip-permissions 2>$null
    Start-Sleep -Seconds 5
    $after  = if (Test-Path $log) { (Get-Content $log | Measure-Object -Line).Lines } else { 0 }
    $delta  = $after - $before
    if ($delta -ge 1) {
        Write-OK "log delta = $delta (hook fired)"
    } else {
        Write-Bad "log delta = 0 -- hook did not fire"
        Write-Hint "check: Get-Content -Tail 5 $log  ; and: venv python -c 'from langfuse import Langfuse'"
        Record-Fail 'hook-no-fire'
    }
}

function Check-TraceApi {
    Write-Step "10. Langfuse traces API: recent trace exists"
    $pk   = Get-SettingsEnv 'LANGFUSE_PUBLIC_KEY'
    $sk   = Get-SettingsEnv 'LANGFUSE_SECRET_KEY'
    $host_= Get-SettingsEnv 'LANGFUSE_HOST'
    if (-not $pk -or -not $sk -or -not $host_) {
        Write-Bad "Langfuse creds missing from ~/.claude/settings.json env block"
        Record-Fail 'langfuse-creds'
        return
    }
    $cred = [pscredential]::new($pk, (ConvertTo-SecureString $sk -AsPlainText -Force))
    try {
        $r = Invoke-RestMethod -Uri "$($host_.TrimEnd('/'))/api/public/traces?limit=1" -Authentication Basic -Credential $cred -TimeoutSec 5
        if ($r.data -and $r.data.Count -gt 0) {
            Write-OK "trace API returned a trace"
        } else {
            Write-Bad "trace API returned no trace"
            Record-Fail 'trace-api'
        }
    } catch {
        Write-Bad "trace API failed: $_"
        Record-Fail 'trace-api'
    }
}

# ===== main =================================================================
Write-Step "healthcheck mode=$Mode  repo=$RepoRoot"
Check-McpConnected
Check-JcodemunchPath
Check-McpTimeout
Check-LangfuseCompose
Check-LangfuseApi
Check-LangfuseSdk
Check-Secrets
if ($Mode -eq 'full') {
    Check-Verify
    Check-SmokeHook
    Check-TraceApi
}

if ($script:ChecksFailed -eq 0) {
    Write-Host "`nHEALTHCHECK: ok"
    exit 0
} else {
    Write-Host ("`nHEALTHCHECK: fail ({0}) -- {1}" -f $script:ChecksFailed, $script:FirstFail)
    exit 1
}
