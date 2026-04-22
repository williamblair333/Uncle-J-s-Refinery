# Every-2-min poll job (Windows). Checks for Telegram reply, upgrades if approved.
param()
$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = $PSScriptRoot
$ProjRoot  = Split-Path $ScriptDir -Parent
$StateFile = Join-Path $ProjRoot "state\stack-alerts-pending.json"
$LogFile   = Join-Path $ProjRoot "state\stack-alerts.log"

function Write-Log([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

if (-not (Test-Path $StateFile)) { exit 0 }

. "$ProjRoot\lib\notify.ps1"

$state     = Get-Content $StateFile | ConvertFrom-Json
$messageId = [long]$state.message_id
$sentAt    = [datetime]::ParseExact($state.sent_at, "yyyy-MM-ddTHH:mm:ssZ", $null)
$packages  = $state.packages
$expiryMin = [int]($env:ALERT_EXPIRY_MINUTES ?? "60")

$elapsedMin = ([datetime]::UtcNow - $sentAt).TotalMinutes
if ($elapsedMin -gt $expiryMin) {
    Write-Log "Alert window expired (>$expiryMin min). Cleaning up state."
    Remove-Item $StateFile -Force
    exit 0
}

$reply = Invoke-NotifyPollReply -MessageId $messageId

switch ($reply) {
    "pending"  { exit 0 }
    "rejected" {
        Write-Log "User skipped upgrade. Cleaning up state."
        Remove-Item $StateFile -Force
        Invoke-NotifySendText -Message "⏭ Upgrade skipped. Will check again tomorrow."
        exit 0
    }
    "approved" {
        Write-Log "User approved upgrade. Invoking Claude..."
        Remove-Item $StateFile -Force

        $pkgList = $packages -join " "
        $upgradePrompt = @"
Upgrade these Python packages in the Uncle J's Refinery venv.
Run exactly: cd $ProjRoot && uv pip install --upgrade $pkgList
Then check if the release notes for these packages require any changes to CLAUDE.md.
Respond with one sentence: what was upgraded and whether CLAUDE.md needed changes.
"@
        $result = "Upgrade failed — run manually: uv pip install --upgrade $pkgList"
        try {
            $result = claude --allowed-tools Bash -p $upgradePrompt 2>$null
        } catch {}

        Write-Log "Upgrade result: $result"
        Invoke-NotifySendText -Message "🔧 $result"
    }
}
