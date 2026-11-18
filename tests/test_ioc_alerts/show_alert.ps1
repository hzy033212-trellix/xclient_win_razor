<#
.SYNOPSIS
  Show an IOC alert straight from hxsim's captured uploads (manual cross-check).

.DESCRIPTION
  Finds the iocmatch upload hxsim received from the daemon that contains a match
  marker, decodes that MatchItem (base64 -> gzip -> JSON) and prints its key
  (condition_id, event_type, match time) and event values. Independent of the
  Python verify logic: only hxsim's rundir\uploads\*.decoded files are read.

  The marker comes from -Marker, or from a test's temp\...\ioc_alert.json via -Test.

.PARAMETER Test
  A test artifact folder: a full path, a path relative to the repo root, or just the
  test folder name (e.g. test_ioc_reg_delete_key), searched under temp\.

.PARAMETER Marker
  A match marker (e.g. from hxsim's "match report match_id=..." line).

.PARAMETER InstallDir
  Folder holding all external dependencies (hxsim is <InstallDir>\hxsim).
  Default: install_dir from the repo's paths.json.

.EXAMPLE
  .\show_alert.ps1 -Test test_ioc_reg_delete_key
.EXAMPLE
  .\show_alert.ps1 -Marker 1642334811339
#>
[CmdletBinding(DefaultParameterSetName = "Test")]
param(
    [Parameter(ParameterSetName = "Test", Mandatory = $true, Position = 0)][string]$Test,
    [Parameter(ParameterSetName = "Marker", Mandatory = $true)][string]$Marker,
    [string]$InstallDir
)
$ErrorActionPreference = "Stop"
# $PSScriptRoot isn't set yet when param() defaults run in Windows PowerShell 5.1.
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$paths = Get-Content (Join-Path $repo "paths.json") -Raw | ConvertFrom-Json
if (-not $InstallDir) { $InstallDir = $paths.install_dir }
$tempDir = $paths.audit_output_dir

# Fail fast unless the dependencies this script reads exist in the install folder.
if (-not (Test-Path $InstallDir -PathType Container)) {
    throw "install folder not found: $InstallDir (use -InstallDir)" }
$missing = @("hxsim", "hxsim\rundir\uploads") |
    Where-Object { -not (Test-Path (Join-Path $InstallDir $_)) }
if ($missing) { throw "missing required dependencies in ${InstallDir}: $($missing -join ', ') (use -InstallDir)" }
$uploads = Join-Path $InstallDir "hxsim\rundir\uploads"
"install dir : $InstallDir"

$expected = $null
if ($PSCmdlet.ParameterSetName -eq "Test") {
    $dir = $Test
    if (-not (Test-Path $dir)) { $dir = Join-Path $repo $Test }
    if (-not (Test-Path $dir)) {
        $dir = Get-ChildItem $tempDir -Directory -Recurse |
            Where-Object Name -eq $Test | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $dir) { throw "test folder not found: $Test" }
    $alertFile = Join-Path $dir "ioc_alert.json"
    if (-not (Test-Path $alertFile)) { throw "no ioc_alert.json in $dir (did the test PASS?)" }
    $expected = Get-Content $alertFile -Raw | ConvertFrom-Json
    $Marker = $expected.marker
    "test folder : $dir"
}
"marker      : $Marker"

$hit = Select-String -Path (Join-Path $uploads "task_*_data_*.decoded") `
    -Pattern "<marker>$Marker</marker>" -List | Select-Object -First 1
if (-not $hit) { throw "marker $Marker not found in any upload under $uploads" }
"upload      : $($hit.Filename)  ($((Get-Item $hit.Path).LastWriteTime))"

[xml]$xml = Get-Content $hit.Path -Raw
$item = $xml.itemList.MatchItem | Where-Object { $_.marker -eq "$Marker" } | Select-Object -First 1
$ms = New-Object IO.MemoryStream(, [Convert]::FromBase64String($item.result))
$gz = New-Object IO.Compression.GZipStream($ms, [IO.Compression.CompressionMode]::Decompress)
$body = (New-Object IO.StreamReader($gz)).ReadToEnd() | ConvertFrom-Json
"reported    : $($item.reported)   source: $($item.source)"

"`n--- key ---"
$body.key | Format-List | Out-String -Width 200 | ForEach-Object { $_.Trim() }
"`n--- event values ---"
$body.values | Format-List | Out-String -Width 200 | ForEach-Object { $_.Trim() }

# Cross-check against the IOC feed and, with -Test, the Razor filter the script used.
$feed = Join-Path $tempDir "hxsim\iocs_all_events.xml"
if (Test-Path $feed) {
    [xml]$ioc = Get-Content $feed -Raw
    $cond = $ioc.indicator.condition | Where-Object { $_.id -eq $body.key.condition_id }
    "`n--- IOC condition ---"
    if ($cond) {
        foreach ($t in @($cond.test)) { "{0} {1} '{2}'" -f $t.value, $t.operator, $t.'#text' }
    } else { "condition $($body.key.condition_id) is NOT in iocs_all_events.xml" }
}
if ($expected) {
    $filter = Get-Content (Join-Path $dir "event_metadata.json") -Raw | ConvertFrom-Json
    $prefix = "$($body.key.event_type)/"
    "`n--- Razor filter check (event_metadata.json vs this alert) ---"
    $allOk = $true
    foreach ($p in $filter.PSObject.Properties) {
        $actual = $body.values."$prefix$($p.Name)"
        $ok = "$actual" -ieq "$($p.Value)"   # case-insensitive, like Razor's path normalisation
        if (-not $ok) { $allOk = $false }
        "{0,-4} {1,-22} expected={2}  actual={3}" -f ($(if ($ok) { "OK" } else { "DIFF" })), $p.Name, $p.Value, $actual
    }
    "`nRESULT: " + $(if ($allOk) { "alert matches the Razor filter" } else { "MISMATCH" })
}
