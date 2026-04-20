<#
.SYNOPSIS
    Installs the reliability layer on top of the MCP stack:
      * our custom skills (prior-art-check, judge) into %USERPROFILE%\.claude\skills\
      * dwarvesf/claude-guardrails (prompt-injection defense) into .claude\ via git
      * prints the two /plugin slash commands to run inside Claude Code
        for Superpowers and Ralph Wiggum

.DESCRIPTION
    Idempotent. Doesn't clobber anything -- if a skill already exists
    at the target, it's updated in place. claude-guardrails is cloned
    if missing, pulled if present.

.PARAMETER SkipGuardrails
    Don't install dwarvesf/claude-guardrails.

.PARAMETER SkipSkills
    Don't copy our custom skills into the global claude dir.
#>

[CmdletBinding()]
param(
    [switch]$SkipGuardrails,
    [switch]$SkipSkills
)

$ErrorActionPreference = 'Stop'
$StackRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
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

# Ensure ~/.claude exists
if (-not (Test-Path $ClaudeDir)) { New-Item -ItemType Directory -Path $ClaudeDir | Out-Null }

# --- 1. Copy custom skills -------------------------------------------------
if (-not $SkipSkills) {
    $SkillsDst = Join-Path $ClaudeDir 'skills'
    if (-not (Test-Path $SkillsDst)) { New-Item -ItemType Directory -Path $SkillsDst | Out-Null }

    Write-Step "Installing custom skills to $SkillsDst"
    foreach ($s in @('prior-art-check','judge')) {
        $src = Join-Path $StackRoot "skills\$s"
        $dst = Join-Path $SkillsDst $s
        if (-not (Test-Path $src)) { Write-Warn2 "skill source missing: $src"; continue }
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse -Path $src -Destination $dst
        Write-OK "skill installed: $s"
    }
} else {
    Write-Warn2 "-SkipSkills set; not installing our skills"
}

# --- 2. dwarvesf/claude-guardrails ----------------------------------------
# Delegated to install-guardrails.ps1, which calls the upstream install.sh
# via Git Bash. That gets the jq-based deep merge of settings.json right
# (preserves existing jcodemunch hooks). Reimplementing the merge in
# PowerShell proved error-prone, so we shell out.
if (-not $SkipGuardrails) {
    if (-not (Has-Cmd git)) {
        Write-Warn2 "git not found on PATH. Open a new PowerShell and re-run, or pass -SkipGuardrails."
    } else {
        Write-Step "Installing dwarvesf/claude-guardrails via install-guardrails.ps1"
        & (Join-Path $StackRoot 'install-guardrails.ps1')
        if ($LASTEXITCODE -ne 0) {
            Write-Warn2 "install-guardrails.ps1 exited $LASTEXITCODE -- see output above."
        }
    }
} else {
    Write-Warn2 "-SkipGuardrails set; not installing prompt-injection defense"
}

# --- 3. Plugin install instructions ---------------------------------------
Write-Step "Plugins (must be run INSIDE Claude Code, not in PowerShell)"
Write-Host @"

Start Claude Code:
  claude

Then at the prompt, run these slash commands. Ralph lives in a different
marketplace than Superpowers.

  /plugin install superpowers@claude-plugins-official
  /plugin marketplace add anthropics/claude-code
  /plugin install ralph-wiggum@anthropics-claude-code

Superpowers adds 20+ agentic skills (brainstorming, systematic-debugging,
TDD enforcement, verification-before-completion, requesting-code-review).

Ralph Wiggum adds /ralph-loop "your task" --completion-promise "DONE" for
self-referential autonomous loops. For our verification-gated version,
run from PowerShell instead:
  .\ralph-harness.ps1 -PrdPath .\PRD.md -RepoPath C:\path\to\repo

"@ -ForegroundColor White

# --- 4. Summary ------------------------------------------------------------
Write-Step "Installation complete"
Write-Host @"

Reliability layer installed. Components:
  [*] Custom skills copied to $ClaudeDir\skills\{prior-art-check, judge}
  [*] dwarvesf/claude-guardrails cloned to $StackRoot\claude-guardrails
  [ ] Superpowers plugin           -- run /plugin install inside claude
  [ ] Ralph Wiggum plugin          -- run /plugin install inside claude
  [*] Ralph harness available      -- .\ralph-harness.ps1

Read docs\RELIABILITY.md for what each component does and when to turn
it off.

Test the stack:
  claude
  > "review this folder"
  (should see Claude invoke prior-art-check, then jcodemunch, then
  optionally the judge skill before reporting)

"@ -ForegroundColor White
