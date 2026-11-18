<#
.SYNOPSIS
    Builds Trellix XClient (Windows x64) linked against the fake MA SDK.

.DESCRIPTION
    Stage 0  Verify prerequisites; stop and list every unsatisfied one.
    Stage 1  Conan setup (profile/refs/VS x64 environment).
    Stage 2  conan install XClient -> pull all dependency packages.
    Stage 3  Self-test the fake, remove cached ma-sdk, conan create the fake
             under the same reference, re-resolve and prove XClient uses it.
    Stage 4  Configure  (conan build --configure).
    Stage 5  Compile    (conan build --build), then verify the output links the fake.

    Neither external source tree is bundled or modified; both are located via
    the required -XClientSource and -FakeSdkSource options, and everything is
    built under -BuildDir.

.EXAMPLE
    .\build.cmd -XClientSource <dir> -FakeSdkSource <dir>
    .\build.cmd -XClientSource <dir> -FakeSdkSource <dir> -CheckOnly
#>
[CmdletBinding()]
param(
    # Required: external XClient checkout and fake MA SDK source tree.
    [string]$XClientSource = "",
    [string]$FakeSdkSource = "",
    # Empty = .\build next to this script ($PSScriptRoot is empty in Windows
    # PowerShell 5.1 param defaults, so it is resolved below).
    [string]$BuildDir      = "",
    [string]$ConanProfile  = "Windows-x86_64-RelWithDebInfo",
    # XClient's own user/channel. "production" makes XClient's conanfile resolve
    # its dependencies (including ma-sdk) from UnifiedPackages/production.
    [string]$XClientUser    = "UnifiedAgent",
    [ValidateSet("production", "develop")]
    [string]$XClientChannel = "production",
    [switch]$CheckOnly,            # run stage 0 only
    [switch]$SkipFakeTests,        # skip the fake's standalone cl/cmake tests
    [switch]$SkipRemoteCheck,      # don't probe Conan remotes (all packages already cached)
    [switch]$EnableFakeUnitTests   # also build mxservices_unit_test with OPTION_MA_LIVE_TESTS/OPTION_MA_SDK_FAKE
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$missingOpts = @()
if (-not $XClientSource) { $missingOpts += "-XClientSource <path to XClient checkout (contains conanfile.py)>" }
if (-not $FakeSdkSource) { $missingOpts += "-FakeSdkSource <path to ma-sdk-fake source tree (contains conanfile.py, src\, include\)>" }
if ($missingOpts.Count -gt 0) {
    Write-Host "Missing required option(s):" -ForegroundColor Red
    $missingOpts | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Usage: build.cmd -XClientSource <dir> -FakeSdkSource <dir> [-BuildDir <dir>] [-CheckOnly] [...]"
    Write-Host "See README.md for all options."
    exit 2
}
if (-not $BuildDir) { $BuildDir = Join-Path $root "build" }

. (Join-Path $root "lib\Common.ps1")
. (Join-Path $root "lib\Prereqs.ps1")
. (Join-Path $root "lib\Stages.ps1")

function Resolve-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path))
}

# Mirrors XClient conanfile.py configure(): package user honours
# CONAN_PACKAGES_USER; channel is production for production/Orbit builds.
$pkgUser = if ($env:CONAN_PACKAGES_USER -and $env:CONAN_PACKAGES_USER.Trim()) { $env:CONAN_PACKAGES_USER.Trim() } else { "UnifiedPackages" }
$pkgChannel = if ($XClientChannel -eq "production" -or $env:ORBIT_BUILD_ENV) { "production" } else { "develop" }

$Cfg = [pscustomobject]@{
    XClientSource       = Resolve-FullPath $XClientSource
    FakeSdkSource       = Resolve-FullPath $FakeSdkSource
    BuildDir            = Resolve-FullPath $BuildDir
    Profile             = $ConanProfile
    XClientUserChannel  = "$XClientUser/$XClientChannel"
    PackageUserChannel  = "$pkgUser/$pkgChannel"
    MaSdkVersion        = $null
    MaSdkRealRef        = $null
    ConanExe            = $null
    ConanDataDir        = $null
    VsPath              = $null
    SkipFakeTests       = [bool]$SkipFakeTests
    SkipRemoteCheck     = [bool]$SkipRemoteCheck
    EnableFakeUnitTests = [bool]$EnableFakeUnitTests
}

# Never let Conan block on an interactive login prompt.
$env:CONAN_NON_INTERACTIVE = "1"

$logDir = Initialize-LogDir $root
Write-Host "XClient + fake MA SDK build  (logs: $logDir)"

# Git Bash/MSYS put Git\usr\bin on PATH; its perl breaks the XClient build
# (vdev_setup.md #8) and its tools shadow the native ones. Drop it for this
# process so results don't depend on which shell launched the script.
$pathParts = $env:Path -split ';' | Where-Object { $_ }
$msys = @($pathParts | Where-Object { $_ -match '\\Git\\usr\\bin\\?$' } | Select-Object -Unique)
if ($msys.Count -gt 0) {
    $env:Path = ($pathParts | Where-Object { $_ -notmatch '\\Git\\usr\\bin\\?$' }) -join ';'
    Write-Host "  Removed MSYS entries from PATH for this run: $($msys -join '; ')"
}

$Cfg.MaSdkVersion = Get-XClientMaSdkVersion $Cfg.XClientSource
$Cfg.MaSdkRealRef = "ma-sdk/$($Cfg.MaSdkVersion)@$($Cfg.PackageUserChannel)"

if (-not (Test-Prerequisites $Cfg)) {
    Write-Host ""
    Write-Host "Unsatisfied prerequisites ($($script:PrereqFailures.Count)):" -ForegroundColor Red
    $n = 0
    foreach ($f in $script:PrereqFailures) { $n++; Write-Host "  $n. $f" -ForegroundColor Red }
    Stop-Build "fix the prerequisites above and re-run"
}
Write-Host ""
Write-Ok "All prerequisites satisfied$(if ($script:PrereqWarnings.Count) { " ($($script:PrereqWarnings.Count) warning(s))" })"
if ($CheckOnly) { Write-Info "-CheckOnly given; stopping after stage 0."; exit 0 }

$started = Get-Date
Invoke-ConanSetup $Cfg
Invoke-PullPackages $Cfg
Invoke-ReplaceMaSdk $Cfg
Invoke-Configure $Cfg
Invoke-Compile $Cfg
Invoke-Verify $Cfg
Write-Summary $Cfg
Write-Info ("Elapsed: {0:hh\:mm\:ss}" -f ((Get-Date) - $started))
exit 0
