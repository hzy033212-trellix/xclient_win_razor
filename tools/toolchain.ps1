# Where this repo's tools live and how to put them on PATH; dot-sourced by setup.ps1,
# run_tests.ps1 and tools\fakema\Get-FakeMaMsi.ps1.
#
# Everything is installed by setup.ps1 under one short root folder, NWR_ROOT (default
# C:\nwr): the XClient build needs short paths (MAX_PATH), and the Conan cache and the
# fake-MA build are big and must not live in the repo. Nothing here touches the system
# PATH or another tool install: Use-Toolchain changes only the current process.

$script:NwrRoot  = if ($env:NWR_ROOT) { $env:NWR_ROOT } else { 'C:\nwr' }
$script:NwrTools = Join-Path $NwrRoot 'tools'

# Pinned tool versions and their downloads. Everything comes from Trellix Artifactory
# (artifactory.trellix.com; ARTIFACTORY_USER / ARTIFACTORY_TOKEN), FireEye Artifactory
# (artifactory.eng.fireeye.com; anonymous) or GitHub releases - see DEPENDENCIES.md. Each
# Sha256 pins the file (and is how setup.ps1 knows a download is the expected one).
# Source, where set, goes into the tool's .nwr_version marker with its version, so a tool
# installed from an earlier source is reinstalled from this one.
$script:TrellixNuget = 'https://artifactory.trellix.com/artifactory/api/nuget/approved-nuget-remote/Download'
$script:FireEyeWinTools = 'https://artifactory.eng.fireeye.com/Agent-Tools/WinTools'
$script:FireEyePypi = 'https://artifactory.eng.fireeye.com/api/pypi/pypi-endpoint/simple'
$script:Toolchain = [ordered]@{
    # The nuget.org "python" package, through Trellix Artifactory's approved NuGet remote
    # (identical to nuget.org's: same SHA-256).
    Python    = @{ Version = '3.9.13'; Dir = (Join-Path $NwrTools 'python39'); Source = 'trellix-nuget'
                   Url = "$TrellixNuget/python/3.9.13"; Auth = $true
                   Sha256 = 'df29f99c9cf508eda80e878e2795c50ec94431db8d5396a5e455381af593daf4' }
    Git       = @{ Version = '2.47.1'; Dir = (Join-Path $NwrTools 'git')
                   Url = 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/PortableGit-2.47.1-64-bit.7z.exe' }
    CMake     = @{ Version = '3.25.3'; Dir = (Join-Path $NwrTools 'cmake')
                   Url = 'https://github.com/Kitware/CMake/releases/download/v3.25.3/cmake-3.25.3-windows-x86_64.zip' }
    # The msi XClient's vdev_setup.md installs, unpacked with msiexec /a (no install).
    Perl      = @{ Version = '5.32.1.1'; Dir = (Join-Path $NwrTools 'perl'); Source = 'fireeye-wintools'
                   Url = "$FireEyeWinTools/strawberry-perl-5.32.1.1-64bit.msi"
                   Sha256 = '241a881670164feb0b91bb69d39fbbf84c981bec0d9f8c19959f8f48fd177768' }
    # node.exe and npm 2.15.11 from the official msi (unpacked with msiexec /a), node.lib
    # from nodejs.zip (lib\x64\node.lib); both from vdev_setup.md.
    Node012   = @{ Version = '0.12.18'; Dir = (Join-Path $NwrTools 'node012'); Source = 'fireeye-wintools'
                   MsiUrl = "$FireEyeWinTools/node-v0.12.18-x64.msi"
                   MsiSha256 = '674e9f58b6d26c052076b6a75fd12bc25aa19aa79d86e79a092ab77caaf1cbae'
                   LibZipUrl = "$FireEyeWinTools/nodejs.zip"
                   LibZipSha256 = '755ad156b9f2acea612e7a87c04cacbd4a1271813f21e5f044f17438f2964643' }
    Conan     = @{ Version = '1.65.0'; Dir = (Join-Path $NwrTools 'conan-venv'); Source = 'fireeye-pypi'
                   IndexUrl = $FireEyePypi
                   ConfigUrl = 'http://artifactory.eng.fireeye.com/Unified-Build/conan/conan_config_trellix_unified_v2.2.zip' }
    # nuget.org packages, through Trellix Artifactory's approved NuGet remote.
    Dtf       = @{ Version = '4.0.5'; Dir = (Join-Path $NwrTools 'dtf'); Source = 'trellix-nuget'
                   Packages = [ordered]@{
                       'WixToolset.Dtf.WindowsInstaller'         = '624f87a7bd20cf0a69ebf4e179633a66b694e7d8887be94c7b40ad958c75064a'
                       'WixToolset.Dtf.WindowsInstaller.Package' = '10907308884feac09f5447c94b90a3b82b2b34d576d00378e2e0af3a0ad04141'
                       'WixToolset.Dtf.Compression'              = '5e62d4f19029a89d0ade46dbd92ccf86e450c0e66f0c6e275aa4fc2a470b4558'
                       'WixToolset.Dtf.Compression.Cab'          = '407d6f046a04afb514f9ed42a7adf6a02a2bcd794dcd998927d6e91008e153f2' } }
    # Only used when no VS 2022 with the x64 C++ toolset is installed (it is on the runner).
    # Microsoft's bootstrapper: Artifactory has no VS 2022 Build Tools (see DEPENDENCIES.md).
    # MsvcPrefix: the MSVC toolset XClient is built with (VS 2022 17.5, 14.35; the runner has it as
    # its default toolset). Current VS 2022 releases default to MSVC 14.4x, so on those
    # MsvcComponent adds 14.35 side by side (VC\Tools\MSVC\14.35.*). The fake-MA build selects it
    # (vcvars64.bat -vcvars_ver; tools\fakema\build\lib\Common.ps1 $MsvcVersionPrefix).
    # SdkComponent: Windows SDK 10.0.22621, which the WDK below needs and XClient's
    # FindWdkTools.cmake expects (Windows Kits\10\bin\10.0.22621.0).
    VsBuildTools = @{ Url = 'https://aka.ms/vs/17/release/vs_buildtools.exe'
                      MsvcPrefix = '14.35'
                      MsvcComponent = 'Microsoft.VisualStudio.Component.VC.14.35.17.5.x86.x64'
                      SdkVersion = '10.0.22621.0'
                      SdkComponent = 'Microsoft.VisualStudio.Component.Windows11SDK.22621' }
    # Windows Driver Kit 10.0.22621.382 (Windows 11 22H2), the one the runner has: XClient's build
    # takes StampInf.exe from Windows Kits\10\bin\10.0.22621.0. Microsoft's installer (the WDK is
    # not on Artifactory; see DEPENDENCIES.md). go.microsoft.com/fwlink/?linkid=2196230
    Wdk          = @{ Version = '10.1.22621.382'
                      Url = 'https://download.microsoft.com/download/c/6/4/c64e8e90-4143-4e86-93d7-0209b0b30626/wdk/wdksetup.exe'
                      Sha256 = 'F3948D1486F8A7821BCEF431487D3893FCD3A053D97AB37A1333A0C26E0BD232' }
}

# The text setup.ps1 keeps in <tool dir>\.nwr_version: the version, plus the source if set.
function Get-ToolMarker($Tool) {
    if ($Tool.Source) { "$($Tool.Version) $($Tool.Source)" } else { $Tool.Version }
}
# Conan's home (its cache: every XClient dependency package, and the fake ma-sdk
# that shadows the real one) - separate from any other Conan use on the host.
$script:ConanUserHome = $NwrRoot
# The fake-MA build: XClient and ma-sdk-fake checkouts, build tree, Orbit and fake-MA msi.
$script:FakeMaWork = Join-Path $NwrRoot 'fakema'

function Get-ToolPath([string]$Name) {
    $t = $Toolchain[$Name]
    switch ($Name) {
        'Python'  { Join-Path $t.Dir 'python.exe' }
        'Git'     { Join-Path $t.Dir 'cmd\git.exe' }
        'Bash'    { Join-Path $Toolchain.Git.Dir 'bin\bash.exe' }
        'CMake'   { Join-Path $t.Dir 'bin\cmake.exe' }
        'Perl'    { Join-Path $t.Dir 'perl\bin\perl.exe' }
        'Node012' { Join-Path $t.Dir 'node.exe' }
        'Conan'   { Join-Path $t.Dir 'Scripts\conan.exe' }
    }
}

# VS 2022 with the x64 C++ toolset (the same vswhere query the fake-MA build's
# prerequisite check uses).
function Get-Vs2022Install {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { return $null }
    $p = & $vswhere -latest -products * -version '[17.0,18.0)' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
    if ($p -and (Test-Path (Join-Path $p 'VC\Auxiliary\Build\vcvars64.bat'))) { return $p }
    return $null
}

# True if the VS install at $VsPath has the pinned MSVC toolset (VC\Tools\MSVC\14.35.*).
function Test-PinnedMsvc([string]$VsPath) {
    $prefix = $Toolchain.VsBuildTools.MsvcPrefix
    [bool](Get-ChildItem (Join-Path $VsPath 'VC\Tools\MSVC') -Directory -Filter "$prefix.*" -ErrorAction SilentlyContinue)
}

# Windows Kits\10\bin\<SdkVersion>\x64: the folder XClient's FindWdkTools.cmake takes its tools from.
function Get-WinKitsBin {
    Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin\$($Toolchain.VsBuildTools.SdkVersion)\x64"
}
# True if Windows SDK 10.0.22621 is installed (its signtool.exe and um\windows.h).
function Test-PinnedSdk {
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
    (Test-Path (Join-Path (Get-WinKitsBin) 'signtool.exe')) -and
        (Test-Path (Join-Path $kits "Include\$($Toolchain.VsBuildTools.SdkVersion)\um\windows.h"))
}
# True if WDK 10.0.22621 is installed (its StampInf.exe next to the SDK tools, and km headers).
function Test-PinnedWdk {
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
    (Test-Path (Join-Path (Get-WinKitsBin) 'stampinf.exe')) -and
        (Test-Path (Join-Path $kits "Include\$($Toolchain.VsBuildTools.SdkVersion)\km\wdm.h"))
}

# Put this repo's tools first on PATH for this process. -Build adds what the XClient
# build needs on top (CMake, Strawberry Perl, Node 0.12.18, Conan) and drops Git's
# MSYS folder (its perl breaks the build).
function Use-Toolchain([switch]$Build) {
    $dirs = @($Toolchain.Python.Dir, (Join-Path $Toolchain.Python.Dir 'Scripts'), (Join-Path $Toolchain.Git.Dir 'cmd'))
    if ($Build) {
        $dirs += @((Join-Path $Toolchain.CMake.Dir 'bin'), (Join-Path $Toolchain.Perl.Dir 'perl\bin'),
                   (Join-Path $Toolchain.Perl.Dir 'perl\site\bin'), (Join-Path $Toolchain.Perl.Dir 'c\bin'),
                   $Toolchain.Node012.Dir, (Join-Path $Toolchain.Conan.Dir 'Scripts'))
        $env:CONAN_USER_HOME = $ConanUserHome
        $env:CONAN_NON_INTERACTIVE = '1'
    }
    $rest = $env:Path -split ';' | Where-Object { $_ -and ($dirs -notcontains $_) -and ($_ -notmatch '\\Git\\usr\\bin\\?$') }
    $env:Path = (($dirs | Where-Object { Test-Path $_ }) + $rest) -join ';'
    # Read by tests\util\paths.py (RAZOR_<KEY> overrides paths.json): Git Bash for HXSim's gen-certs.sh.
    if (Test-Path (Get-ToolPath 'Bash')) { $env:RAZOR_BASH_EXE = Get-ToolPath 'Bash' }
}

# Download $Url to $Dest unless it is already there (with -Sha256: and has that hash).
# -Auth logs in to Trellix Artifactory with ARTIFACTORY_USER / ARTIFACTORY_TOKEN.
function Get-Download([string]$Url, [string]$Dest, [string]$Sha256, [switch]$Auth) {
    if ((Test-Path $Dest) -and (-not $Sha256 -or (Get-FileHash $Dest -Algorithm SHA256).Hash -eq $Sha256)) { return $Dest }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Write-Host "  downloading $Url"
    $ProgressPreference = 'SilentlyContinue'   # the progress bar slows Invoke-WebRequest down a lot
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $headers = @{}
    if ($Auth) {
        if (-not $env:ARTIFACTORY_USER -or -not $env:ARTIFACTORY_TOKEN) {
            throw "set ARTIFACTORY_USER and ARTIFACTORY_TOKEN to download $Url"
        }
        $pair = [Text.Encoding]::ASCII.GetBytes("$($env:ARTIFACTORY_USER):$($env:ARTIFACTORY_TOKEN)")
        $headers.Authorization = 'Basic ' + [Convert]::ToBase64String($pair)
    }
    Invoke-WebRequest -Uri $Url -OutFile "$Dest.part" -Headers $headers -UseBasicParsing
    if ($Sha256) {
        $actual = (Get-FileHash "$Dest.part" -Algorithm SHA256).Hash
        if ($actual -ne $Sha256) { Remove-Item "$Dest.part" -Force; throw "$Url SHA-256 mismatch: got $actual, expected $Sha256" }
    }
    Move-Item "$Dest.part" $Dest -Force
    return $Dest
}

# Unpack an msi into $Dest without installing it (administrative install: msiexec /a).
function Expand-Msi([string]$Msi, [string]$Dest) {
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    $log = "$Dest.log"
    $p = Start-Process msiexec.exe -ArgumentList '/a', "`"$Msi`"", '/qn', "TARGETDIR=`"$Dest`"", '/l*', "`"$log`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "msiexec /a $Msi failed ($($p.ExitCode)); see $log" }
    Remove-Item $log -Force -ErrorAction SilentlyContinue
}
