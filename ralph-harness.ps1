<#
.SYNOPSIS
    Ralph loop harness chained with our stack's verification tools.

.DESCRIPTION
    The classic Ralph pattern (Geoffrey Huntley) is:
        while true; do claude -p "@PROMPT.md" --dangerously-skip-permissions; done

    This wrapper does the same thing with three upgrades:
      1. Uses a PRD.md file as the stable memory (progress lives on disk,
         not in the context window).
      2. Between iterations, runs our stack's verification gates:
            - jcodemunch `get_changed_symbols`  (what actually moved?)
            - jcodemunch `get_untested_symbols` (what lacks coverage?)
            - jcodemunch `get_pr_risk_profile`  (composite risk score)
         and refuses to declare "done" if risk > threshold or untested
         additions are non-zero without explicit override.
      4. Adds a hard iteration cap so Ralph can't run away.

    The idea: Ralph keeps looping until BOTH the model says "done" AND the
    structural gates agree. That removes the classic Ralph failure mode
    where the model confidently declares victory on an incomplete / broken
    change.

.PARAMETER PrdPath
    Path to a markdown file describing the task. Ralph reads this every
    iteration. See prd-template.md for a starting point.

.PARAMETER RepoPath
    Path to the repo being worked on. Defaults to current directory.

.PARAMETER MaxIterations
    Safety cap. Default 30. Ralph stops no matter what at this count.

.PARAMETER RiskThreshold
    Composite PR risk above which the done-check fails. Default 0.65.
    jcodemunch's get_pr_risk_profile returns 0.0-1.0.

.PARAMETER SkipJudge
    If set, don't run the per-iteration verification gate. Faster but
    weaker -- use only on cosmetic tasks.

.PARAMETER DryRun
    Print what would happen without invoking claude.

.EXAMPLE
    .\ralph-harness.ps1 -PrdPath .\PRD.md -RepoPath C:\work\myrepo

.EXAMPLE
    .\ralph-harness.ps1 -PrdPath .\PRD.md -MaxIterations 50 -RiskThreshold 0.5
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PrdPath,
    [string]$RepoPath = (Get-Location).Path,
    [int]$MaxIterations = 30,
    [double]$RiskThreshold = 0.65,
    [switch]$SkipJudge,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "    OK  $m" -ForegroundColor Green }
function Write-Warn2{ param($m) Write-Host "    !!  $m" -ForegroundColor Yellow }
function Write-Stop { param($m) Write-Host "    X   $m" -ForegroundColor Red }

# --- PATH refresh so 'claude' resolves even in a stale shell -------------
try {
    $m = [System.Environment]::GetEnvironmentVariable('Path','Machine')
    $u = [System.Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$m;$u"
} catch { }

# --- Input validation ----------------------------------------------------
if (-not (Test-Path $PrdPath))  { throw "PRD file not found: $PrdPath" }
if (-not (Test-Path $RepoPath)) { throw "Repo path not found: $RepoPath" }
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    throw "'claude' CLI not found on PATH. Install Claude Code or open a new PowerShell."
}

$PrdPath  = (Resolve-Path $PrdPath).Path
$RepoPath = (Resolve-Path $RepoPath).Path

Write-Step "Ralph harness starting"
Write-OK "PRD        : $PrdPath"
Write-OK "Repo       : $RepoPath"
Write-OK "MaxIter    : $MaxIterations"
Write-OK "RiskCap    : $RiskThreshold"
Write-OK "Judge      : $(if ($SkipJudge) { 'OFF' } else { 'ON' })"
Write-OK "DryRun     : $(if ($DryRun) { 'YES' } else { 'NO' })"

# --- Prompt that Claude runs every iteration -----------------------------
$innerPrompt = @"
Follow the PRD at `"$PrdPath`".

Rules for this iteration:
1. Re-read the PRD from disk. Do NOT assume earlier iterations' context is in memory.
2. Consult MemPalace for prior work on this PRD topic BEFORE editing.
3. Use jcodemunch / serena for code navigation. Do not Read large files.
4. Make the smallest change that advances the PRD.
5. Update the PRD's 'Progress' section at the end with one-line status.
6. If the PRD is complete by your assessment, also write a ``DONE`` marker
   line as the FIRST line of the Progress section, then stop.
"@

# --- Verification gate ---------------------------------------------------
function Invoke-DoneGate {
    param([string]$RepoPath, [double]$Threshold)

    # We invoke claude in non-interactive mode with a query that uses our
    # jcodemunch tools to produce a one-line verdict.
    $gatePrompt = @"
Run the following jcodemunch tools against the git working tree of $RepoPath:
  get_changed_symbols()
  get_untested_symbols(changed_only=true)
  get_pr_risk_profile()

Then print EXACTLY one line of JSON (no markdown, no commentary), of shape:
{"risk": <float>, "untested_count": <int>, "verdict": "done" | "continue", "why": "<short reason>"}

Decide 'done' only if: risk < $Threshold AND untested_count == 0 AND the
PRD's first-progress-line starts with 'DONE'.
"@
    Write-Step "Gate: asking Claude to inspect change + risk"
    Push-Location $RepoPath
    try {
        $gateOutput = & claude -p $gatePrompt 2>&1 | Out-String
    } finally {
        Pop-Location
    }

    # Try to parse the last JSON object in the output
    $line = ($gateOutput -split "`n" | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1)
    if (-not $line) {
        Write-Warn2 "Gate did not return parseable JSON; assuming continue."
        return [pscustomobject]@{ verdict='continue'; risk=$null; untested_count=$null; why='no JSON from gate' }
    }
    try { return ($line | ConvertFrom-Json) }
    catch {
        Write-Warn2 "JSON parse failed: $_"
        return [pscustomobject]@{ verdict='continue'; risk=$null; untested_count=$null; why='unparseable' }
    }
}

# --- Main loop -----------------------------------------------------------
$iter = 0
$startTime = Get-Date
while ($iter -lt $MaxIterations) {
    $iter++
    Write-Step "Iteration $iter / $MaxIterations"

    if ($DryRun) {
        Write-OK "[dry-run] would call: (cd $RepoPath; claude -p <innerPrompt> --dangerously-skip-permissions)"
    } else {
        # Write prompt to temp so we're not shell-escape-fighting
        $tmp = [System.IO.Path]::GetTempFileName() + '.md'
        Set-Content -Path $tmp -Value $innerPrompt -Encoding UTF8
        Push-Location $RepoPath
        try {
            & claude -p "@$tmp" --dangerously-skip-permissions
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "claude exited $LASTEXITCODE on iter $iter; continuing."
            }
        } finally {
            Pop-Location
            Remove-Item -Path $tmp -ErrorAction SilentlyContinue
        }
    }

    if ($SkipJudge) {
        Write-Warn2 "SkipJudge set; not running done-gate. Relying on PRD 'DONE' marker only."
        $prd = Get-Content $PrdPath -Raw
        if ($prd -match '(?m)^\s*DONE\b') {
            Write-OK "PRD marked DONE; stopping."
            break
        }
        continue
    }

    $gate = Invoke-DoneGate -RepoPath $RepoPath -Threshold $RiskThreshold
    Write-Host "    gate: risk=$($gate.risk) untested=$($gate.untested_count) verdict=$($gate.verdict) why=$($gate.why)"

    if ($gate.verdict -eq 'done') {
        Write-OK "Done-gate approved. Exiting loop cleanly at iter $iter."
        break
    }
}

$elapsed = (Get-Date) - $startTime
Write-Step "Ralph harness finished"
Write-OK "Iterations  : $iter"
Write-OK "Elapsed     : $($elapsed.ToString())"
Write-OK "Final PRD   : $PrdPath"

if ($iter -ge $MaxIterations) {
    Write-Warn2 "Max iterations reached without a 'done' verdict. Inspect the PRD and the repo diff manually."
    exit 2
}
