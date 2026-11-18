<#
.SYNOPSIS
    Host housekeeping for the GitHub Actions workflow (.github\workflows\tests.yml).

.DESCRIPTION
    -WaitIdle      Wait until no other GitHub Actions job runs on this host (another runner, e.g.
                   one of another repo, may install or uninstall XClient / MA at the same time).
                   Gives up after -TimeoutMinutes with exit code 1.
    -RebootIfPending
                   If an XClient uninstall left drivers to delete at boot (the next install would
                   be refused), schedule a reboot in -DelaySeconds, so the next job finds a clean
                   host. The runner service starts again after the boot. Skipped (with a warning)
                   while another job runs on this host.

    Other jobs are the Runner.Worker processes that are not an ancestor of this script.
#>
param(
    [switch]$WaitIdle,
    [switch]$RebootIfPending,
    [int]$TimeoutMinutes = 180,
    [int]$DelaySeconds = 60
)

$ErrorActionPreference = 'Stop'

function Get-OtherJobs {
    $procs = @{}
    Get-CimInstance Win32_Process | ForEach-Object { $procs[[int]$_.ProcessId] = $_ }
    $ancestors = @{}
    $id = $PID
    while ($procs.ContainsKey($id) -and -not $ancestors.ContainsKey($id)) {
        $ancestors[$id] = $true
        $id = [int]$procs[$id].ParentProcessId
    }
    @($procs.Values | Where-Object { $_.Name -eq 'Runner.Worker.exe' -and -not $ancestors.ContainsKey([int]$_.ProcessId) } |
      ForEach-Object { "$($_.ProcessId) $($_.ExecutablePath)" })
}

if ($WaitIdle) {
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ($true) {
        $others = Get-OtherJobs
        if (-not $others.Count) { Write-Host 'No other GitHub Actions job runs on this host.'; break }
        if ((Get-Date) -gt $deadline) {
            Write-Host "Another job still runs on this host after $TimeoutMinutes min: $($others -join '; ')"; exit 1
        }
        Write-Host "Waiting for another job on this host to finish: $($others -join '; ')"
        Start-Sleep -Seconds 60
    }
}

if ($RebootIfPending) {
    # The same check as run_tests.ps1's pre-flight.
    $pending = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
    if (-not ($pending | Where-Object { $_ -match '\\drivers\\mfe|McAfee|Trellix' })) {
        Write-Host 'No reboot pending from an XClient uninstall.'; exit 0
    }
    $others = Get-OtherJobs
    if ($others.Count) {
        Write-Warning "A reboot is pending, but another job runs on this host ($($others -join '; ')); not rebooting. The next run's pre-flight will refuse until the host is rebooted."
        exit 0
    }
    Write-Host "A reboot is pending from the XClient uninstall; rebooting in $DelaySeconds s."
    & shutdown.exe /r /t $DelaySeconds /c "new_win_razor CI: reboot after the XClient uninstall" /d p:4:1
    exit $LASTEXITCODE
}
