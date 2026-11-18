<#
.SYNOPSIS
    Installs everything this repo needs on a fresh Windows host. Safe to re-run: only what is
    missing (or at another version) is installed.

.DESCRIPTION
    Into NWR_ROOT (default C:\nwr; tools\toolchain.ps1 has the pinned versions, downloads and
    SHA-256s; every download is from Trellix / FireEye Artifactory or GitHub, see DEPENDENCIES.md):
      python39\     Python 3.9.13 (nuget.org package via Trellix Artifactory; no installer, no
                    registry, not on the system PATH)
      git\          PortableGit 2.47.1 (GitHub; git, Git Bash for HXSim's gen-certs.sh, Git Credential Manager)
    and the repo's venv (venv\, from python39, with requirements.txt from FireEye's PyPI index).

    For the fake-MA XClient build (skipped with -TestsOnly):
      Visual Studio 2022 Build Tools with the C++ workload, MSVC 14.35 and Windows SDK 10.0.22621,
        installed (or those two components added) with Microsoft's bootstrapper if missing
      Windows Driver Kit 10.0.22621.382 (Microsoft's wdksetup.exe; StampInf.exe etc.)
      cmake\        CMake 3.25.3            (GitHub; XClient's cmake_minimum_required)
      perl\         Strawberry Perl 5.32.1.1 (FireEye Artifactory msi, unpacked; XClient's
                    find_package(Perl); not Git's perl)
      node012\      Node.js 0.12.18 + node.lib + npm 2.15.11 (FireEye Artifactory; XClient links node.lib)
      conan-venv\   Conan 1.65.0 (FireEye's PyPI index), with its home (cache) in NWR_ROOT\.conan:
                    the Trellix Conan config installed and its remotes logged in with
                    ARTIFACTORY_USER / ARTIFACTORY_TOKEN
      dtf\          WiX DTF 4.0.5 (nuget.org packages via Trellix Artifactory): patches the fake
                    mxAgent.dll into the Orbit msi

    A tool already installed at the same version but from an earlier source (its .nwr_version
    marker has no source) is reinstalled from the current one.

    What can't be installed: Administrator rights, network access to artifactory.trellix.com
    (ARTIFACTORY_USER / ARTIFACTORY_TOKEN), artifactory.eng.fireeye.com, github.com and
    github.trellix.com (Git Credential Manager sign-in or XCLIENT_GITHUB_TOKEN).

.PARAMETER TestsOnly
    Only what running the tests needs (Python, venv, Git) - enough with -Msi pointing at an msi
    you already have. The default (everything) is needed for run_tests.ps1 to build the fake-MA
    msi of the latest XClient itself.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1
#>
[CmdletBinding()]
param([switch]$TestsOnly)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $repoDir 'tools\toolchain.ps1')
$downloads = Join-Path $NwrRoot 'downloads'
# Files from Trellix / FireEye Artifactory: kept apart from older downloads of the same name
# from the publishers' sites, so those are never taken for them.
$artDownloads = Join-Path $downloads 'artifactory'
$problems = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Message) { Write-Host ''; Write-Host "=== $Message" -ForegroundColor Cyan }
function Test-Marker([string]$Dir, [string]$Version) {
    $m = Join-Path $Dir '.nwr_version'
    (Test-Path $m) -and ((Get-Content $m -Raw).Trim() -eq $Version)
}
function Set-Marker([string]$Dir, [string]$Version) { Set-Content (Join-Path $Dir '.nwr_version') $Version }
function Reset-Dir([string]$Dir) {
    if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
}
# Unzip $Zip into $Dest; with -StripTop the zip's single top folder is dropped.
function Expand-To([string]$Zip, [string]$Dest, [switch]$StripTop) {
    $tmp = "$Dest.unzip"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    $z = if ($Zip -like '*.zip') { $Zip } else { Copy-Item $Zip "$Zip.zip" -Force; "$Zip.zip" }
    Expand-Archive -Path $z -DestinationPath $tmp -Force
    $src = if ($StripTop) { (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName } else { $tmp }
    Get-ChildItem $src -Force | Move-Item -Destination $Dest -Force
    Remove-Item $tmp -Recurse -Force
}
function Invoke-Checked([string]$What, [scriptblock]$Block) {
    try { & $Block }
    catch { Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red; $problems.Add("${What}: $($_.Exception.Message)") }
}

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run setup.ps1 as Administrator.' -ForegroundColor Red; exit 2
}
New-Item -ItemType Directory -Force -Path $NwrTools, $downloads | Out-Null
Write-Host "Tools root : $NwrRoot (NWR_ROOT)"

# ---------------------------------------------------------------------------------------------
Write-Step "Python $($Toolchain.Python.Version)"
Invoke-Checked 'Python' {
    $t = $Toolchain.Python
    if (Test-Marker $t.Dir (Get-ToolMarker $t)) { Write-Host "  present: $($t.Dir)"; return }
    Reset-Dir $t.Dir
    $pkg = Get-Download $t.Url (Join-Path $artDownloads "python.$($t.Version).nupkg") -Sha256 $t.Sha256 -Auth:$t.Auth
    $tmp = Join-Path $downloads 'python-nupkg'
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Copy-Item $pkg "$pkg.zip" -Force
    Expand-Archive "$pkg.zip" $tmp -Force
    Get-ChildItem (Join-Path $tmp 'tools') -Force | Move-Item -Destination $t.Dir -Force
    Remove-Item $tmp -Recurse -Force
    & (Get-ToolPath 'Python') -m ensurepip --upgrade | Out-Null
    $v = & (Get-ToolPath 'Python') --version
    if ($v -notmatch [regex]::Escape($t.Version)) { throw "unexpected $v" }
    Set-Marker $t.Dir (Get-ToolMarker $t)
    Write-Host "  installed: $v"
}

Write-Step "PortableGit $($Toolchain.Git.Version)"
Invoke-Checked 'Git' {
    $t = $Toolchain.Git
    if (Test-Marker $t.Dir (Get-ToolMarker $t)) { Write-Host "  present: $($t.Dir)"; return }
    Reset-Dir $t.Dir
    $sfx = Get-Download $t.Url (Join-Path $downloads "PortableGit-$($t.Version)-64-bit.7z.exe")
    $p = Start-Process $sfx -ArgumentList "-o`"$($t.Dir)`"", '-y' -Wait -PassThru
    if ($p.ExitCode -ne 0 -or -not (Test-Path (Get-ToolPath 'Git'))) { throw "PortableGit extract failed ($($p.ExitCode))" }
    Set-Marker $t.Dir (Get-ToolMarker $t)
    Write-Host "  installed: $(& (Get-ToolPath 'Git') --version)"
}

Write-Step 'venv (tests)'
Invoke-Checked 'venv' {
    $venvPython = Join-Path $repoDir 'venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        & (Get-ToolPath 'Python') -m venv (Join-Path $repoDir 'venv')
        if ($LASTEXITCODE -ne 0) { throw "python -m venv failed ($LASTEXITCODE)" }
    }
    $req = Join-Path $repoDir 'requirements.txt'
    $mark = Join-Path $repoDir 'venv\.requirements.sha256'
    $sha = (Get-FileHash $req).Hash
    if ((Test-Path $mark) -and (Get-Content $mark -Raw).Trim() -eq $sha) { Write-Host "  requirements up to date"; return }
    # requirements.txt names FireEye's index; --isolated ignores pip.ini / PIP_* settings, so
    # no other index (e.g. an extra-index-url from the host's pip config) is used.
    & $venvPython -m pip install --isolated --disable-pip-version-check -q -r $req
    if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements.txt failed ($LASTEXITCODE)" }
    Set-Content $mark $sha
    Write-Host "  requirements installed"
}

if (-not $TestsOnly) {
    # -----------------------------------------------------------------------------------------
    Write-Step 'Visual Studio 2022 Build Tools (C++)'
    Invoke-Checked 'Visual Studio 2022' {
        $vt = $Toolchain.VsBuildTools
        $vs = Get-Vs2022Install
        $what = "MSVC $($vt.MsvcPrefix), Windows SDK $($vt.SdkVersion)"
        if ($vs -and (Test-PinnedMsvc $vs) -and (Test-PinnedSdk)) { Write-Host "  present: $vs ($what)"; return }
        $exe = Get-Download $vt.Url (Join-Path $downloads 'vs_buildtools.exe')
        if ($vs) {
            # VS 2022 without MSVC 14.35 (a current release defaults to 14.4x) or SDK 10.0.22621
            # (it ships 10.0.26100): add the missing components. The Build Tools bootstrapper
            # modifies Build Tools installs only; for another edition add "MSVC v143 ...
            # (v14.35-17.5)" and "Windows 11 SDK (10.0.22621.0)" in the Visual Studio Installer.
            Write-Host "  adding $what to $vs ..."
            $vsArgs = @('modify', '--installPath', "`"$vs`"", '--add', $vt.MsvcComponent, '--add', $vt.SdkComponent,
                        '--quiet', '--wait', '--norestart', '--nocache')
        } else {
            Write-Host '  installing (about 8 GB, 30-60 min) ...'
            $vsArgs = @('--quiet', '--wait', '--norestart', '--nocache',
                        '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended',
                        '--add', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                        '--add', $vt.MsvcComponent, '--add', $vt.SdkComponent)
        }
        $p = Start-Process $exe -ArgumentList $vsArgs -Wait -PassThru
        if ($p.ExitCode -eq 3010) { Write-Host '  installed; Windows asks for a reboot' -ForegroundColor Yellow }
        elseif ($p.ExitCode -ne 0) { throw "$(Split-Path $exe -Leaf) exit code $($p.ExitCode)" }
        $vs = Get-Vs2022Install
        if (-not $vs) { throw 'VS 2022 with the x64 C++ toolset still not found after the install' }
        if (-not (Test-PinnedMsvc $vs)) { throw "MSVC $($vt.MsvcPrefix) still not found in $vs\VC\Tools\MSVC after the install" }
        if (-not (Test-PinnedSdk)) { throw "Windows SDK $($vt.SdkVersion) still not found in $(Get-WinKitsBin) after the install" }
        Write-Host "  installed: $vs ($what)"
    }

    Write-Step "Windows Driver Kit $($Toolchain.Wdk.Version)"
    Invoke-Checked 'WDK' {
        $t = $Toolchain.Wdk
        if (Test-PinnedWdk) { Write-Host "  present: $(Get-WinKitsBin)\stampinf.exe"; return }
        if (-not (Test-PinnedSdk)) { throw "needs Windows SDK $($Toolchain.VsBuildTools.SdkVersion) (the step above) first" }
        $exe = Get-Download $t.Url (Join-Path $downloads "wdksetup_$($t.Version).exe") -Sha256 $t.Sha256
        Write-Host '  installing (about 2 GB, 5-15 min) ...'
        $log = Join-Path $downloads 'wdksetup.log'
        $p = Start-Process $exe -ArgumentList @('/features', '+', '/quiet', '/norestart', '/ceip', 'off', '/log', "`"$log`"") -Wait -PassThru
        if ($p.ExitCode -eq 3010) { Write-Host '  installed; Windows asks for a reboot' -ForegroundColor Yellow }
        elseif ($p.ExitCode -ne 0) { throw "wdksetup.exe exit code $($p.ExitCode) (log: $log)" }
        if (-not (Test-PinnedWdk)) { throw "StampInf.exe still not found in $(Get-WinKitsBin) after the install (log: $log)" }
        Write-Host "  installed: $(Get-WinKitsBin)\stampinf.exe"
    }

    Write-Step "CMake $($Toolchain.CMake.Version)"
    Invoke-Checked 'CMake' {
        $t = $Toolchain.CMake
        if (Test-Marker $t.Dir (Get-ToolMarker $t)) { Write-Host "  present: $($t.Dir)"; return }
        Reset-Dir $t.Dir
        Expand-To (Get-Download $t.Url (Join-Path $downloads (Split-Path $t.Url -Leaf))) $t.Dir -StripTop
        Set-Marker $t.Dir (Get-ToolMarker $t)
        Write-Host "  installed: $((& (Get-ToolPath 'CMake') --version)[0])"
    }

    Write-Step "Strawberry Perl $($Toolchain.Perl.Version)"
    Invoke-Checked 'Perl' {
        $t = $Toolchain.Perl
        if (Test-Marker $t.Dir (Get-ToolMarker $t)) { Write-Host "  present: $($t.Dir)"; return }
        Reset-Dir $t.Dir
        $msi = Get-Download $t.Url (Join-Path $artDownloads (Split-Path $t.Url -Leaf)) -Sha256 $t.Sha256
        $tmp = Join-Path $downloads 'perl-msi'
        Expand-Msi $msi $tmp
        Get-ChildItem (Join-Path $tmp 'Strawberry') -Force | Move-Item -Destination $t.Dir -Force
        Remove-Item $tmp -Recurse -Force
        # The msi's installer would rewrite the build-time path (C:\strawberry\) in the files
        # relocation.txt lists (Config.pm, the .bat wrappers, ...); msiexec /a doesn't, so do it here.
        $reloc = Join-Path $t.Dir 'relocation.txt'
        $lines = @(Get-Content $reloc)
        $old = $lines[0].Trim()                            # C:\strawberry\
        $new = $t.Dir.TrimEnd('\') + '\'
        # The path appears as C:\strawberry\, C:\\strawberry\\ or C:/strawberry/ (file:// URLs);
        # none of the three matches inside another, so every listed file gets all three.
        $pairs = @(@($old, $new), @($old.Replace('\', '\\'), $new.Replace('\', '\\')),
                   @($old.Replace('\', '/'), $new.Replace('\', '/')))
        $latin1 = [Text.Encoding]::GetEncoding(28591)       # byte-preserving
        foreach ($line in $lines | Select-Object -Skip 1) {
            if ($line -notmatch '^(.+):\w+$') { continue }
            $file = Join-Path $t.Dir $Matches[1]
            if (-not (Test-Path $file)) { continue }
            $text = $fixed = $latin1.GetString([IO.File]::ReadAllBytes($file))
            foreach ($p in $pairs) {
                $fixed = [regex]::Replace($fixed, [regex]::Escape($p[0]), $p[1].Replace('$', '$$'), 'IgnoreCase')
            }
            if ($fixed -ne $text) { [IO.File]::WriteAllBytes($file, $latin1.GetBytes($fixed)) }
        }
        Set-Marker $t.Dir (Get-ToolMarker $t)
        Write-Host "  installed: $(& (Get-ToolPath 'Perl') -e 'print $^V')"
    }

    Write-Step "Node.js $($Toolchain.Node012.Version) (+ node.lib, npm 2.15.11)"
    Invoke-Checked 'Node.js 0.12.18' {
        $t = $Toolchain.Node012
        if (Test-Marker $t.Dir (Get-ToolMarker $t)) { Write-Host "  present: $($t.Dir)"; return }
        Reset-Dir $t.Dir
        # node.exe and npm 2.15.11 (node_modules\npm) from the official msi, unpacked, not installed.
        $msi = Get-Download $t.MsiUrl (Join-Path $artDownloads (Split-Path $t.MsiUrl -Leaf)) -Sha256 $t.MsiSha256
        $tmp = Join-Path $downloads 'node012-msi'
        Expand-Msi $msi $tmp
        Copy-Item (Join-Path $tmp 'nodejs\node.exe') $t.Dir
        New-Item -ItemType Directory -Force -Path (Join-Path $t.Dir 'node_modules') | Out-Null
        Move-Item (Join-Path $tmp 'nodejs\node_modules\npm') (Join-Path $t.Dir 'node_modules\npm')
        Remove-Item $tmp -Recurse -Force
        Copy-Item (Join-Path $t.Dir 'node_modules\npm\bin\npm.cmd') (Join-Path $t.Dir 'npm.cmd')
        # node.lib (x64), which XClient links, from nodejs.zip.
        $zip = Get-Download $t.LibZipUrl (Join-Path $artDownloads 'nodejs.zip') -Sha256 $t.LibZipSha256
        New-Item -ItemType Directory -Force -Path (Join-Path $t.Dir 'lib\x64') | Out-Null
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            $entry = $archive.GetEntry('nodejs/lib/x64/node.lib')
            if (-not $entry) { throw "no nodejs/lib/x64/node.lib in $zip" }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $t.Dir 'lib\x64\node.lib'), $true)
        } finally { $archive.Dispose() }
        Set-Marker $t.Dir (Get-ToolMarker $t)
        Write-Host "  installed: node $(& (Get-ToolPath 'Node012') --version), npm $(& cmd /c (Join-Path $t.Dir 'npm.cmd') --version)"
    }

    Write-Step "Conan $($Toolchain.Conan.Version) (home: $ConanUserHome\.conan)"
    Invoke-Checked 'Conan' {
        $t = $Toolchain.Conan
        if (-not (Test-Marker $t.Dir (Get-ToolMarker $t))) {
            Reset-Dir $t.Dir
            & (Get-ToolPath 'Python') -m venv $t.Dir
            # --isolated: no pip.ini / PIP_* settings, so FireEye's index is the only one used.
            & (Join-Path $t.Dir 'Scripts\python.exe') -m pip install --isolated --disable-pip-version-check -q `
                --index-url $t.IndexUrl --trusted-host ([uri]$t.IndexUrl).Host "conan==$($t.Version)"
            if ($LASTEXITCODE -ne 0) { throw "pip install conan failed ($LASTEXITCODE)" }
            Set-Marker $t.Dir (Get-ToolMarker $t)
        }
        $env:CONAN_USER_HOME = $ConanUserHome
        $env:CONAN_NON_INTERACTIVE = '1'
        $conan = Get-ToolPath 'Conan'
        # Conan writes warnings to stderr; judge it by its exit code, not by stderr output.
        $ErrorActionPreference = 'Continue'
        Write-Host "  $(& $conan --version 2>&1)"
        function Get-ConanRemotes {
            @(& $conan remote list 2>&1 | ForEach-Object { "$_" } |
              Where-Object { $_ -match '^([^:\s]+):\s+(https?://\S+)' } |
              ForEach-Object { [pscustomobject]@{ Name = ($_ -split ':')[0]; Url = ($_ -split '\s+')[1] } })
        }
        # A new Conan home has only the default conancenter remote: install the Trellix config.
        if (-not (Get-ConanRemotes | Where-Object { $_.Url -match 'artifactory' })) {
            Write-Host "  installing the Trellix Conan config: $($t.ConfigUrl)"
            & $conan config install $t.ConfigUrl 2>&1 | ForEach-Object { Write-Host "    $_" }
            if ($LASTEXITCODE -ne 0) { throw "conan config install failed ($LASTEXITCODE)" }
        }
        $remotes = @(Get-ConanRemotes | Where-Object { $_.Url -match 'artifactory' } | ForEach-Object Name)
        if (-not $remotes) { throw 'no Artifactory Conan remote after the config install' }
        & $conan profile show Windows-x86_64-RelWithDebInfo *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Conan profile Windows-x86_64-RelWithDebInfo missing after the config install' }
        if (-not $env:ARTIFACTORY_USER -or -not $env:ARTIFACTORY_TOKEN) {
            throw 'set ARTIFACTORY_USER and ARTIFACTORY_TOKEN to log in to the Conan remotes'
        }
        $loggedIn = 0
        foreach ($r in $remotes) {
            & $conan user -r $r -p $env:ARTIFACTORY_TOKEN $env:ARTIFACTORY_USER *> $null
            if ($LASTEXITCODE -eq 0) { $loggedIn++; Write-Host "  logged in to remote $r" }
            else { Write-Host "  remote ${r}: login failed (unreachable, or other credentials needed)" -ForegroundColor Yellow }
        }
        if ($loggedIn -eq 0) { throw "could not log in to any Conan remote ($($remotes -join ', '))" }
    }

    Write-Step "WiX DTF $($Toolchain.Dtf.Version) (msi patching)"
    Invoke-Checked 'WiX DTF' {
        $t = $Toolchain.Dtf
        if (Test-Marker $t.Dir (Get-ToolMarker $t)) { Write-Host "  present: $($t.Dir)"; return }
        Reset-Dir $t.Dir
        foreach ($id in $t.Packages.Keys) {
            $lid = $id.ToLower()
            $pkg = Get-Download "$TrellixNuget/$id/$($t.Version)" (Join-Path $artDownloads "$lid.$($t.Version).nupkg") `
                                -Sha256 $t.Packages[$id] -Auth
            $tmp = Join-Path $downloads "$lid-unpack"
            if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
            Copy-Item $pkg "$pkg.zip" -Force
            Expand-Archive "$pkg.zip" $tmp -Force
            # Windows PowerShell runs on .NET Framework: take the framework build of the assembly.
            $lib = Get-ChildItem (Join-Path $tmp 'lib') -Directory | Where-Object { $_.Name -match '^net\d' } |
                   Sort-Object Name | Select-Object -First 1
            if (-not $lib) { throw "no .NET Framework assembly in $id" }
            Copy-Item (Join-Path $lib.FullName '*.dll') $t.Dir
            Remove-Item $tmp -Recurse -Force
        }
        Set-Marker $t.Dir (Get-ToolMarker $t)
        Write-Host "  installed: $((Get-ChildItem $t.Dir -Filter *.dll).Name -join ', ')"
    }
}

Write-Host ''
if ($problems.Count) {
    foreach ($p in $problems) { Write-Host "SETUP PROBLEM: $p" -ForegroundColor Red }
    exit 1
}
Write-Host "Setup complete$(if ($TestsOnly) { ' (tests only)' })." -ForegroundColor Green
exit 0
