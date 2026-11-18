<#
.SYNOPSIS
    Records host memory and the memory of the processes a test run uses, every -Interval seconds,
    into a CSV, until the process -ParentPid exits (run_tests.ps1 starts it with its own PID).

.DESCRIPTION
    Columns: time, free physical MB, committed MB, commit limit MB, then the private MB and
    working set MB of each watched process name (all its instances summed), and the test pytest
    last dropped an audit task for (from -PytestLog, if given).
#>
param(
    [Parameter(Mandatory = $true)][string]$Csv,
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [int]$Interval = 30,
    [string]$PytestLog = ''
)

$names = 'xclient', 'node', 'python', 'MsMpEng', 'msiexec', 'msedgewebview2', 'msedge', 'claude'
$header = @('time', 'free_mb', 'commit_mb', 'commit_limit_mb')
foreach ($n in $names) { $header += "${n}_priv_mb", "${n}_ws_mb" }
$header += 'current_test'
Set-Content -Path $Csv -Value ($header -join ',') -Encoding ascii

while (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
    $os = Get-CimInstance Win32_OperatingSystem
    $row = @(
        (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss'),
        [int]($os.FreePhysicalMemory / 1KB),
        [int](($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / 1KB),
        [int]($os.TotalVirtualMemorySize / 1KB)
    )
    $procs = Get-Process -ErrorAction SilentlyContinue
    foreach ($n in $names) {
        $p = $procs | Where-Object { $_.ProcessName -eq $n }
        $row += [int](($p | Measure-Object PrivateMemorySize64 -Sum).Sum / 1MB)
        $row += [int](($p | Measure-Object WorkingSet64 -Sum).Sum / 1MB)
    }
    $test = ''
    if ($PytestLog -and (Test-Path $PytestLog)) {
        $m = Select-String -Path $PytestLog -Pattern 'Task (test_\S+) \(' | Select-Object -Last 1
        if ($m) { $test = $m.Matches[0].Groups[1].Value }
    }
    $row += $test
    Add-Content -Path $Csv -Value ($row -join ',') -Encoding ascii
    Start-Sleep -Seconds $Interval
}
