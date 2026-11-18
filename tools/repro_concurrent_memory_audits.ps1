<#
.SYNOPSIS
    Reproduces XClient processes-memory returning invalid pid-0 ProcessItems and duplicated
    processes, by running several all-process processes-memory audits at the same time.

.DESCRIPTION
    Needs XClient installed (e.g. run_tests.ps1 -KeepInstalled) and an administrator prompt.
    Each round starts -Parallel copies of
        xclient.exe -f tests\audit_scripts\test_processes_memory_all_processes_no_options_schema_validate.json -o <dir>
    at once, waits for all of them, and checks every processes-memory.json for:
      - invalid entries: a ProcessItem with pid 0 or no Username
      - duplicates: the same pid and startTime listed more than once
    See XCLIENT_BUG_INVALID_PID0_PROCESS_ITEMS.md and XCLIENT_BUG_DUPLICATE_PROCESS_ITEMS.md.

    Exit code: 0 = reproduced (at least one round had an anomaly), 1 = not reproduced.

.PARAMETER Rounds
    Number of rounds. Default 5.
.PARAMETER Parallel
    Audits started together in each round. Default 8. With 1 the audits run one at a time
    (the control: no anomaly was seen in 80 such audits).
.PARAMETER Out
    Output folder (deleted first). Default C:\repro\concurrent_memory_audits.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\repro_concurrent_memory_audits.ps1 -Rounds 3 -Parallel 8
#>
[CmdletBinding()]
param(
    [int]$Rounds = 5,
    [int]$Parallel = 8,
    [string]$Out = 'C:\repro\concurrent_memory_audits'
)
$ErrorActionPreference = 'Stop'
$repo   = Split-Path -Parent $PSScriptRoot
$xc     = Join-Path $env:ProgramFiles 'Trellix\XClient\xclient.exe'
$script = Join-Path $repo 'tests\audit_scripts\test_processes_memory_all_processes_no_options_schema_validate.json'
if (-not (Test-Path $xc)) { throw "XClient not installed ($xc). Install it first, e.g. run_tests.ps1 -KeepInstalled." }

Remove-Item $Out -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Out | Out-Null
"XClient: $((Get-Item $xc).VersionInfo.ProductVersion)  Windows: $([Environment]::OSVersion.Version)  user: $(whoami)"
"Rounds: $Rounds  Parallel: $Parallel  Output: $Out"

$roundsHit = 0; $auditsInvalid = 0; $auditsDup = 0; $audits = 0
foreach ($i in 1..$Rounds) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $runs = foreach ($k in 1..$Parallel) {
        $dir = Join-Path $Out ("r{0}_{1}" -f $i, $k)
        New-Item -ItemType Directory -Force $dir | Out-Null
        [pscustomobject]@{ Dir = $dir
                           P   = Start-Process $xc -ArgumentList '-f', "`"$script`"", '-o', "`"$dir`"" -WindowStyle Hidden -PassThru }
    }
    $runs | ForEach-Object { $_.P.WaitForExit() }
    "--- round $i ($([int]$sw.Elapsed.TotalSeconds) s)"
    $hit = $false
    foreach ($r in $runs) {
        $audits++
        $name = Split-Path $r.Dir -Leaf
        $json = Join-Path $r.Dir 'processes-memory.json'
        if (-not (Test-Path $json)) { "{0,-8} exit {1}: no processes-memory.json" -f $name, $r.P.ExitCode; continue }
        $items = @((Get-Content $json -Raw | ConvertFrom-Json).ProcessItem)
        $bad = @($items | Where-Object { $_.pid -eq 0 -or -not $_.Username })
        $dups = @($items | Where-Object { $_.pid -ne 0 } | Group-Object { "$($_.pid)|$($_.startTime)" } | Where-Object Count -gt 1)
        if ($bad) { $auditsInvalid++; $hit = $true }
        if ($dups) { $auditsDup++; $hit = $true }
        "{0,-8} items={1} invalid={2} duplicated={3}" -f $name, $items.Count, $bad.Count, $dups.Count
        foreach ($b in $bad) {
            "         invalid: pid={0} name='{1}' parentpid=0x{2:x} startTime={3} kernelTime={4}" -f $b.pid, $b.name, [uint64]$b.parentpid, $b.startTime, $b.kernelTime
        }
        foreach ($d in $dups) {
            $first = $d.Group[0]
            "         duplicated: pid={0} {1} (startTime {2}) x{3}" -f $first.pid, $first.name, $first.startTime, $d.Count
        }
    }
    if ($hit) { $roundsHit++ }
}
""
"SUMMARY: $roundsHit of $Rounds rounds reproduced; audits with invalid entries: $auditsInvalid of $audits; with duplicates: $auditsDup of $audits"
if ($roundsHit) { exit 0 } else { exit 1 }
