# Shared utilities for optional feature installers (Windows).
# Dot-source this file: . "$PSScriptRoot\lib\feature-helpers.ps1"

function Prompt-YesNo {
    param([string]$Question, [string]$Default = "y")
    $hint = if ($Default -eq "y") { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = Read-Host "$Question $hint"
        if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $Default }
        switch ($answer.ToLower()) {
            "y" { return $true  }
            "n" { return $false }
            default { Write-Host "  Please answer y or n." }
        }
    }
}

function Prompt-Value {
    param([string]$Question, [string]$Default = "")
    $prompt = $Question
    if ($Default) { $prompt += " [$Default]" }
    $value = Read-Host $prompt
    if ([string]::IsNullOrWhiteSpace($value)) { $value = $Default }
    return $value
}

# Write or update KEY=VALUE as a user-level Windows environment variable.
function Write-EnvVar {
    param([string]$Key, [string]$Value)
    [Environment]::SetEnvironmentVariable($Key, $Value, "User")
    # Also set in current session so scripts run right after install work.
    Set-Item -Path "Env:\$Key" -Value $Value
}

# Register a Task Scheduler task (idempotent — unregisters first if exists).
function Install-ScheduledTask-Idempotent {
    param(
        [string]$TaskName,
        [string]$ScriptPath,
        [string]$WorkingDir,
        [object]$Trigger   # pass a New-ScheduledTaskTrigger result
    )
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
                 -Argument "-NonInteractive -File `"$ScriptPath`"" `
                 -WorkingDirectory $WorkingDir
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger $Trigger -Settings $settings -RunLevel Highest -Force | Out-Null
}

function Remove-ScheduledTask-Safe {
    param([string]$TaskName)
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}
