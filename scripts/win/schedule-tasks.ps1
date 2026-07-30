# Register the Uncle J maintenance jobs with Windows Task Scheduler.
#
# PowerShell rather than schtasks.exe because schtasks has no flag for
# StartWhenAvailable. Its default is false, meaning a job whose start time
# passes while the machine is off or asleep is skipped entirely rather than run
# on next wake. These jobs are scheduled 01:00-03:00 on a workstation, so the
# schtasks default would register four tasks that never fire once — automation
# that looks present and does nothing.
#
# Invoked by scripts/win/schedule-tasks.sh. Run with -Remove to unregister.

param([switch]$Remove)

$ErrorActionPreference = 'Stop'

$repo   = (Resolve-Path "$PSScriptRoot\..\..").Path
$bash   = "C:\util\apps\Git\bin\bash.exe"
$runner = Join-Path $repo "scripts\win\run-job.sh"

if (-not (Test-Path $bash))   { throw "bash not found at $bash" }
if (-not (Test-Path $runner)) { throw "run-job.sh not found at $runner" }

# Times mirror the cron entries in install.sh:448-451 and the jdocmunch cron.
$jobs = @(
    @{ Name = 'uncle-j-jcodemunch-reindex'; At = '01:00'; Job = 'jcodemunch-reindex' }
    @{ Name = 'uncle-j-jdocmunch-reindex';  At = '01:30'; Job = 'jdocmunch-reindex'  }
    @{ Name = 'uncle-j-memweave-sync';      At = '02:30'; Job = 'memweave-sync'      }
    @{ Name = 'uncle-j-auto-maintain';      At = '03:00'; Job = 'auto-maintain'      }
)

if ($Remove) {
    foreach ($j in $jobs) {
        if (Get-ScheduledTask -TaskName $j.Name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $j.Name -Confirm:$false
            Write-Output "removed: $($j.Name)"
        } else {
            Write-Output "not present: $($j.Name)"
        }
    }
    exit 0
}

# StartWhenAvailable is the whole reason for this file: run a missed job on next
# wake instead of skipping the day. The battery settings keep it firing on a
# laptop, and the 2h limit stops a wedged reindex holding its lock indefinitely.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

foreach ($j in $jobs) {
    $action  = New-ScheduledTaskAction -Execute $bash -Argument "`"$runner`" $($j.Job)" -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Daily -At $j.At
    Register-ScheduledTask -TaskName $j.Name -Action $action -Trigger $trigger `
        -Settings $settings -Description "Uncle J's Refinery: $($j.Job)" -Force | Out-Null
    Write-Output "registered: $($j.Name)  daily $($j.At)  (StartWhenAvailable)"
}
