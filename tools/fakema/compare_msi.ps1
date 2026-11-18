<#
.SYNOPSIS
    Compares two XClient MSIs: the fake-MA msi against the Orbit msi it was made from.

.DESCRIPTION
    1. Authenticode signature of each MSI
    2. Admin-extracts both (msiexec /a) and compares every payload file by
       SHA-256, plus the signer of each PE file. A .cab that differs is expanded and
       its files compared too; if they all match it is reported as SIGNATURE_ONLY
       (the cab is signed at build time, so production and test builds always differ)
    3. Dumps the MSI tables (Property, CustomAction, InstallExecuteSequence, ...)
       to text and diffs them

    Results go under <OutDir> (wiped first): payload_diff.csv, summary.txt. Uses only Windows'
    own msiexec, expand.exe and Windows Installer COM.

.EXAMPLE
    .\tools\fakema\compare_msi.ps1 -Reference <orbit msi> -Candidate <fake-MA msi> -OutDir <folder>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Reference,
    [Parameter(Mandatory)][string]$Candidate,
    [Parameter(Mandatory)][string]$OutDir
)

$ErrorActionPreference = 'Stop'

# Absolute: msiexec /a rejects a relative TARGETDIR (error 1606).
$OutDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)
foreach ($m in $Candidate, $Reference) { if (-not (Test-Path $m)) { throw "MSI not found: '$m'" } }
$Candidate = (Resolve-Path $Candidate).Path
$Reference = (Resolve-Path $Reference).Path

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$summary = New-Object System.Collections.Generic.List[string]
function Say([string]$Line = '') { Write-Host $Line; $summary.Add($Line) }
function Write-Section([string]$Title) { Say ''; Say ('=' * 78); Say "  $Title"; Say ('=' * 78) }

# ---------------------------------------------------------------------------
# MSI table dump via the WindowsInstaller COM API
# ---------------------------------------------------------------------------
$installer = New-Object -ComObject WindowsInstaller.Installer

function Invoke-Com($Object, [string]$Method, [object[]]$ArgList) {
    $Object.GetType().InvokeMember($Method, [Reflection.BindingFlags]::InvokeMethod, $null, $Object, $ArgList)
}
function Get-ComProp($Object, [string]$Name, [object[]]$ArgList = @()) {
    $Object.GetType().InvokeMember($Name, [Reflection.BindingFlags]::GetProperty, $null, $Object, $ArgList)
}

function Get-MsiRows($Db, [string]$Sql) {
    $view = Invoke-Com $Db 'OpenView' @($Sql)
    Invoke-Com $view 'Execute' @() | Out-Null
    $cols = Get-ComProp $view 'ColumnInfo' @(0)
    $n = Get-ComProp $cols 'FieldCount'
    $rows = @()
    while ($rec = Invoke-Com $view 'Fetch' @()) {
        $vals = for ($i = 1; $i -le $n; $i++) {
            # Binary streams can't be read as strings - mark them instead.
            try { Get-ComProp $rec 'StringData' @($i) } catch { '<binary>' }
        }
        $rows += ($vals -join "`t")
    }
    Invoke-Com $view 'Close' @() | Out-Null
    $rows
}

function Export-MsiTables([string]$Msi, [string]$Dest) {
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $db = Invoke-Com $installer 'OpenDatabase' @($Msi, 0)
    $tables = Get-MsiRows $db 'SELECT `Name` FROM `_Tables`' | Sort-Object
    foreach ($t in $tables) {
        $rows = try { Get-MsiRows $db "SELECT * FROM ``$t``" } catch { @("<error: $($_.Exception.Message)>") }
        # -Value (not the pipeline) so empty tables still get a file.
        Set-Content (Join-Path $Dest "$t.txt") -Value @($rows | Sort-Object) -Encoding UTF8
    }
    [Runtime.InteropServices.Marshal]::ReleaseComObject($db) | Out-Null
    $tables
}

function Get-MsiProperty([string]$Msi, [string]$Name) {
    $db = Invoke-Com $installer 'OpenDatabase' @($Msi, 0)
    $v = Get-MsiRows $db "SELECT ``Value`` FROM ``Property`` WHERE ``Property``='$Name'"
    [Runtime.InteropServices.Marshal]::ReleaseComObject($db) | Out-Null
    $v
}

# Values expected to differ between any two builds; the table diff flags them as "expected".
$expectedProps = 'ProductVersion', 'ProductCode', 'PackageCode'

# ---------------------------------------------------------------------------
# 1. Signatures and basics
# ---------------------------------------------------------------------------
Write-Section '1. MSI files'
foreach ($pair in @(@('Reference', $Reference), @('Candidate', $Candidate))) {
    $f = Get-Item $pair[1]
    $sig = Get-AuthenticodeSignature $f.FullName
    Say ("{0,-10}: {1}" -f $pair[0], $f.FullName)
    Say ("            size {0:N1} MB, version {1}, ProductCode {2}" -f ($f.Length / 1MB),
         (Get-MsiProperty $f.FullName 'ProductVersion'), (Get-MsiProperty $f.FullName 'ProductCode'))
    Say ("            UpgradeCode {0}" -f (Get-MsiProperty $f.FullName 'UpgradeCode'))
    Say ("            signature {0}: {1}" -f $sig.Status, $sig.SignerCertificate.Subject)
}

# ---------------------------------------------------------------------------
# 2. Table diff
# ---------------------------------------------------------------------------
Write-Section '2. MSI tables'
$refTabDir = Join-Path $OutDir 'tables\reference'
$canTabDir = Join-Path $OutDir 'tables\candidate'
$refTables = Export-MsiTables $Reference $refTabDir
$canTables = Export-MsiTables $Candidate $canTabDir
$tableDiff = Join-Path $OutDir 'tables_diff.txt'
'' | Set-Content $tableDiff

foreach ($t in ($refTables + $canTables | Sort-Object -Unique)) {
    $rf = Join-Path $refTabDir "$t.txt"; $cf = Join-Path $canTabDir "$t.txt"
    if (-not (Test-Path $rf)) { Say "  only in candidate : table $t"; continue }
    if (-not (Test-Path $cf)) { Say "  only in reference : table $t"; continue }
    $r = @(Get-Content $rf); $c = @(Get-Content $cf)
    $d = Compare-Object $r $c
    if (-not $d) { continue }
    $label = if ($t -eq 'Property' -and -not ($d | Where-Object { ($_.InputObject -split "`t")[0] -notin $expectedProps })) { ' (expected: version/codes only)' } else { '' }
    Say ("  {0,-28} {1} row(s) differ{2}" -f $t, $d.Count, $label)
    Add-Content $tableDiff "### $t"
    $d | ForEach-Object { Add-Content $tableDiff ("{0} {1}" -f $(if ($_.SideIndicator -eq '<=') { 'REF' } else { 'CAN' }), $_.InputObject) }
    Add-Content $tableDiff ''
}
Say "  Details: $tableDiff"

# ---------------------------------------------------------------------------
# 3. Payload diff (admin install)
# ---------------------------------------------------------------------------
Write-Section '3. Payload files (admin extract)'
function Expand-Msi([string]$Msi, [string]$Dest) {
    $log = "$Dest.log"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $p = Start-Process msiexec.exe -ArgumentList "/a `"$Msi`" /qn TARGETDIR=`"$Dest`" /l*v `"$log`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Admin extract of $Msi failed ($($p.ExitCode)). See $log" }
}
$refX = Join-Path $OutDir 'extract\reference'
$canX = Join-Path $OutDir 'extract\candidate'
Expand-Msi $Reference $refX
Expand-Msi $Candidate $canX

function Get-PayloadIndex([string]$Dir) {
    $idx = @{}
    Get-ChildItem $Dir -Recurse -File | Where-Object { $_.Extension -ne '.msi' } | ForEach-Object {
        $idx[$_.FullName.Substring($Dir.Length + 1)] = $_
    }
    $idx
}
$refIdx = Get-PayloadIndex $refX
$canIdx = Get-PayloadIndex $canX
$peExt = '.exe', '.dll', '.sys', '.cat', '.ps1', '.cab'

function Expand-Cab([string]$Cab, [string]$Dest) {
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    & "$env:SystemRoot\System32\expand.exe" "-F:*" $Cab $Dest | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "expand of $Cab failed ($LASTEXITCODE)" }
    $h = @{}
    Get-ChildItem $Dest -Recurse -File | ForEach-Object { $h[$_.FullName.Substring($Dest.Length + 1)] = (Get-FileHash $_.FullName).Hash }
    $h
}
# Returns the inner files that differ between two cabs (empty = same contents)
function Compare-Cab([string]$Rel, [string]$RefCab, [string]$CanCab) {
    $r = Expand-Cab $RefCab (Join-Path $OutDir "cab\reference\$Rel")
    $c = Expand-Cab $CanCab (Join-Path $OutDir "cab\candidate\$Rel")
    @($r.Keys + $c.Keys | Sort-Object -Unique | Where-Object { $r[$_] -ne $c[$_] })
}

$rows = foreach ($k in ($refIdx.Keys + $canIdx.Keys | Sort-Object -Unique)) {
    $r = $refIdx[$k]; $c = $canIdx[$k]
    $rh = if ($r) { (Get-FileHash $r.FullName).Hash }
    $ch = if ($c) { (Get-FileHash $c.FullName).Hash }
    $status = if (-not $r) { 'ONLY_CANDIDATE' } elseif (-not $c) { 'ONLY_REFERENCE' } elseif ($rh -eq $ch) { 'SAME' } else { 'DIFFERENT' }
    $rs = $cs = ''
    $cabDiff = @()
    if ($status -eq 'DIFFERENT' -and [IO.Path]::GetExtension($k) -eq '.cab') {
        $cabDiff = Compare-Cab $k $r.FullName $c.FullName
        if (-not $cabDiff) { $status = 'SIGNATURE_ONLY' }
    }
    if ($status -in 'DIFFERENT', 'SIGNATURE_ONLY' -and $peExt -contains [IO.Path]::GetExtension($k).ToLower()) {
        $rs = (Get-AuthenticodeSignature $r.FullName).SignerCertificate.Subject
        $cs = (Get-AuthenticodeSignature $c.FullName).SignerCertificate.Subject
    }
    $rv = if ($r) { $r.VersionInfo.FileVersion }
    $cv = if ($c) { $c.VersionInfo.FileVersion }
    [pscustomobject]@{
        Status = $status; File = $k
        RefSize = $r.Length; CanSize = $c.Length
        RefVersion = $rv; CanVersion = $cv
        RefSigner = $rs; CanSigner = $cs
        RefSha256 = $rh; CanSha256 = $ch
        CabFilesDiffering = $cabDiff -join '; '
    }
}
$csv = Join-Path $OutDir 'payload_diff.csv'
$rows | Export-Csv $csv -NoTypeInformation

$rows | Group-Object Status | Sort-Object Name | ForEach-Object { Say ("  {0,-15} {1}" -f $_.Name, $_.Count) }
$notSame = $rows | Where-Object Status -ne 'SAME'
if ($notSame) {
    Say ''
    Say '  Files that are not identical:'
    foreach ($x in $notSame) {
        Say ("   [{0}] {1}" -f $x.Status, $x.File)
        if ($x.RefSigner -or $x.CanSigner) { Say ("       signer ref: {0}`n       signer can: {1}" -f $x.RefSigner, $x.CanSigner) }
        if ($x.Status -eq 'SIGNATURE_ONLY') { Say '       contents identical; only the signature differs' }
        if ($x.CabFilesDiffering) { Say ("       files in cab that differ: {0}" -f $x.CabFilesDiffering) }
        if ($x.RefVersion -ne $x.CanVersion) { Say ("       version ref: {0}  can: {1}" -f $x.RefVersion, $x.CanVersion) }
    }
}
Say "  Details: $csv"

$summary | Set-Content (Join-Path $OutDir 'summary.txt') -Encoding UTF8
Write-Host ''
Write-Host "Summary saved to $(Join-Path $OutDir 'summary.txt')" -ForegroundColor Cyan
