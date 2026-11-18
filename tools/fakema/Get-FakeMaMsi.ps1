<#
.SYNOPSIS
    Makes sure the Orbit msi and the fake-MA msi of an XClient version (default: the latest passed
    build) are ready, building the fake-MA mxAgent.dll only when needed.

.DESCRIPTION
    1. Version: the newest passed Orbit installer build of -Release ('latest', Artifactory.ps1
       Find-LatestPassedOrbit), or the one given.
    2. Orbit msi -> NWR_ROOT\fakema\orbit\ (downloaded unless already there with the right SHA-256).
    3. Fake-MA XClient (build_fake_xclient.py): built only if the XClient commit behind the version,
       the ma-sdk-fake commit or the build tooling changed since the last build; otherwise reused.
    4. Fake-MA msi -> NWR_ROOT\fakema\msi\xclient_fakema_<version>_x64.msi: the Orbit msi with the fake
       mxAgent.dll swapped in (patch_msi.ps1), then compared with the Orbit msi (compare_msi.ps1), which
       must differ only in mxAgent.dll. Skipped if it was already made from the same Orbit msi and
       mxAgent.dll.
    Prints VERSION=, ORBIT_MSI=, FAKEMA_MSI= and FAKEMA_BIN= lines (read by run_tests.ps1).
    Needs setup.ps1 (toolchain), ARTIFACTORY_USER / ARTIFACTORY_TOKEN and github.trellix.com access.

.PARAMETER Version
    'latest' (default) or a full Orbit version such as 50.4.0.174.

.PARAMETER Release
    XClient release whose latest build is taken. Default: XCLIENT_RELEASE, else 50.4.0.

.PARAMETER Force
    Rebuild the fake-MA XClient and remake the msi even if nothing changed.
#>
[CmdletBinding()]
param(
    [string]$Version = 'latest',
    [string]$Release = $(if ($env:XCLIENT_RELEASE) { $env:XCLIENT_RELEASE } else { '50.4.0' }),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoDir = Split-Path (Split-Path $here)
. (Join-Path $repoDir 'tools\toolchain.ps1')
. (Join-Path $here 'Artifactory.ps1')
$python = Join-Path $repoDir 'venv\Scripts\python.exe'
function Write-Step([string]$Message) { Write-Host ''; Write-Host "=== $Message" -ForegroundColor Cyan }

foreach ($tool in 'Python', 'Git', 'CMake', 'Perl', 'Node012', 'Conan') {
    if (-not (Test-Path (Get-ToolPath $tool))) { throw "$tool not found ($(Get-ToolPath $tool)): run setup.ps1" }
}
$vs = Get-Vs2022Install
if (-not $vs) { throw 'Visual Studio 2022 with the x64 C++ toolset not found: run setup.ps1' }
if (-not (Test-PinnedMsvc $vs)) { throw "MSVC $($Toolchain.VsBuildTools.MsvcPrefix) not found in $vs\VC\Tools\MSVC: run setup.ps1" }
if (-not (Test-PinnedSdk)) { throw "Windows SDK $($Toolchain.VsBuildTools.SdkVersion) not found ($(Get-WinKitsBin)): run setup.ps1" }
if (-not (Test-PinnedWdk)) { throw "WDK $($Toolchain.Wdk.Version) not found (no stampinf.exe in $(Get-WinKitsBin)): run setup.ps1" }
Use-Toolchain -Build
$headers = Get-ArtifactoryHeaders

Write-Step 'XClient version'
if ($Version -eq 'latest') {
    $orbit = Find-LatestPassedOrbit $Release $headers
    Write-Host "Latest passed build of $Release : $($orbit.Version)"
} elseif ($Version -match '^(\d+\.\d+\.\d+)\.(\d+)$') {
    $orbit = Find-OrbitMsi $Matches[1] ([int]$Matches[2]) $headers
} else {
    throw "-Version must be 'latest' or look like 50.4.0.174, not '$Version'"
}
$v = $orbit.Version

Write-Step "Orbit msi $v"
$orbitMsi = Join-Path $FakeMaWork "orbit\$(($orbit.Path -split '/')[-1])"
Get-Artifact $orbit.Path $orbitMsi $headers

Write-Step "Fake-MA XClient at the commit $v was built from"
$pyArgs = @((Join-Path $here 'build_fake_xclient.py'), '--version', $v, '--work', $FakeMaWork)
if ($Force) { $pyArgs += '--force' }
$out = & $python @pyArgs | ForEach-Object { Write-Host $_; $_ }
if ($LASTEXITCODE -ne 0) { throw "Fake-MA XClient build failed (exit code $LASTEXITCODE)" }
$install = ($out | Where-Object { $_ -like 'XCLIENT_INSTALL=*' } | Select-Object -Last 1) -replace '^XCLIENT_INSTALL=', ''
if (-not $install) { throw 'build_fake_xclient.py did not report its install folder' }
$bin = Join-Path $install 'bin'
$mxAgent = Join-Path $bin 'mxAgent.dll'

Write-Step "Fake-MA msi $v"
$fakeMsi = Join-Path $FakeMaWork "msi\xclient_fakema_${v}_x64.msi"
$sourceFile = "$fakeMsi.source.json"
$source = @{ orbit = (Get-FileHash $orbitMsi).Hash; mxAgent = (Get-FileHash $mxAgent).Hash } | ConvertTo-Json -Compress
if (-not $Force -and (Test-Path $fakeMsi) -and (Test-Path $sourceFile) -and (Get-Content $sourceFile -Raw).Trim() -eq $source) {
    Write-Host "  up to date: $fakeMsi"
} else {
    if (Test-Path $sourceFile) { Remove-Item $sourceFile -Force }
    & (Join-Path $here 'patch_msi.ps1') -Msi $orbitMsi -MxAgent $mxAgent -Out $fakeMsi
    $compareDir = Join-Path $FakeMaWork "compare\$v"
    & (Join-Path $here 'compare_msi.ps1') -Candidate $fakeMsi -Reference $orbitMsi -OutDir $compareDir | Out-Null
    $notSame = @(Import-Csv (Join-Path $compareDir 'payload_diff.csv') | Where-Object Status -ne 'SAME')
    if ($notSame.Count -ne 1 -or (Split-Path $notSame[0].File -Leaf) -ne 'mxAgent.dll' -or $notSame[0].Status -ne 'DIFFERENT') {
        $notSame | ForEach-Object { Write-Host "  [$($_.Status)] $($_.File)" -ForegroundColor Red }
        throw "Expected mxAgent.dll to be the only payload file that differs from Orbit $v (see $compareDir)"
    }
    Write-Host "  identical to Orbit $v except mxAgent.dll (compare: $compareDir)"
    Set-Content $sourceFile $source
}

Write-Host ''
"VERSION=$v"
"ORBIT_MSI=$orbitMsi"
"FAKEMA_MSI=$fakeMsi"
"FAKEMA_BIN=$bin"
