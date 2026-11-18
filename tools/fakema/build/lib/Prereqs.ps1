# Stage 0: prerequisite checks. Every check runs; all failures are collected
# and printed together so one pass shows everything that needs fixing.

$script:PrereqFailures = New-Object System.Collections.Generic.List[string]
$script:PrereqWarnings = New-Object System.Collections.Generic.List[string]

function Add-PrereqResult([bool]$Ok, [string]$Name, [string]$Detail, [string]$Fix) {
    if ($Ok) { Write-Ok "$Name - $Detail"; return }
    Write-Fail "$Name - $Detail"
    $msg = "$Name : $Detail"
    if ($Fix) { $msg += "`n           fix: $Fix" }
    $script:PrereqFailures.Add($msg)
}

function Add-PrereqWarning([string]$Name, [string]$Detail) {
    Write-Warn2 "$Name - $Detail"
    $script:PrereqWarnings.Add("$Name : $Detail")
}

# Resolves the first executable named $Name on PATH, skipping the Windows
# Store "App Execution Alias" stubs (WindowsApps\python.exe etc.).
function Find-Tool([string]$Name) {
    $cmds = @(Get-Command $Name -All -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch '\\WindowsApps\\' })
    if ($cmds.Count -gt 0) { return $cmds[0].Source }
    return $null
}

function Test-ToolVersion([string]$Name, [string]$Exe, [string[]]$VersionArgs,
                          [version]$Min, [version]$MaxExclusive, [string]$Fix) {
    $path = Find-Tool $Exe
    if (-not $path) { Add-PrereqResult $false $Name "'$Exe' not found on PATH" $Fix; return $null }
    $out = Get-NativeOutput $path $VersionArgs
    $ver = Get-VersionFromText $out
    if (-not $ver) { Add-PrereqResult $false $Name "could not read version from '$path'" $Fix; return $null }
    $ok = ($ver -ge $Min) -and (-not $MaxExclusive -or $ver -lt $MaxExclusive)
    $range = ">= $Min" + $(if ($MaxExclusive) { " and < $MaxExclusive" } else { "" })
    Add-PrereqResult $ok $Name "$ver at $path (need $range)" $Fix
    return $path
}

function Test-Prerequisites($Cfg) {
    Write-Banner "Stage 0/5 - Prerequisite checks"

    # --- Host -----------------------------------------------------------------
    $isWin64 = ($env:OS -eq "Windows_NT") -and [Environment]::Is64BitOperatingSystem
    Add-PrereqResult $isWin64 "Host OS" "Windows x64 required (found OS=$env:OS, 64-bit=$([Environment]::Is64BitOperatingSystem))" ""

    # --- Visual Studio 2022 / MSVC v143 ----------------------------------------
    $vs = Get-Vs2022Path
    if ($vs) {
        $all = @(Get-ChildItem (Join-Path $vs "VC\Tools\MSVC") -Directory -ErrorAction SilentlyContinue | ForEach-Object Name)
        $msvc = Get-PinnedMsvcDir $vs
        $vcvars = Test-Path (Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat")
        Add-PrereqResult ([bool]$msvc -and $vcvars) "Visual Studio 2022" `
            "$vs (MSVC $script:MsvcVersionPrefix needed; installed toolsets: $($all -join ', '))" `
            "Run setup.ps1 (adds Microsoft.VisualStudio.Component.VC.14.35.17.5.x86.x64), or add 'MSVC v143 - VS 2022 C++ x64/x86 build tools (v14.35-17.5)' in the Visual Studio Installer"
        $Cfg.VsPath = $vs
    } else {
        Add-PrereqResult $false "Visual Studio 2022" "no VS 17.x install with the x64 C++ toolset found via vswhere" `
            "Install VS 2022 17.5 'Desktop development with C++' (vdev_setup.md Build Toolchain #1)"
    }

    # --- Build tools required by XClient's CMake / conanfiles ------------------
    # cmake_minimum_required(VERSION 3.25.3) in XClient CMakeLists.txt
    Test-ToolVersion "CMake" "cmake" @("--version") ([version]"3.25.3") $null `
        "Install CMake 3.25.3 and add it to PATH (vdev_setup.md #6)" | Out-Null
    # conanfiles use 'from conans import' => Conan 1.x only; required_conan_version >=1.34.1
    $Cfg.ConanExe = Test-ToolVersion "Conan" "conan" @("--version") ([version]"1.34.1") ([version]"2.0") `
        "pip install conan==1.59.0 (vdev_setup.md #14); Conan 2.x is not supported"
    # find_package(Git 1.8.3.1 REQUIRED), find_package(PythonInterp 2.7.5 REQUIRED), find_package(Perl 5.10 REQUIRED)
    Test-ToolVersion "Git" "git" @("--version") ([version]"1.8.3.1") $null "Install Git 2.39.2 (vdev_setup.md #7)" | Out-Null
    Test-ToolVersion "Python" "python" @("--version") ([version]"2.7.5") $null `
        "Install Python 3.11.2 and add it to PATH (vdev_setup.md #10)" | Out-Null
    $perl = Test-ToolVersion "Perl" "perl" @("-v") ([version]"5.10") $null `
        "Install Strawberry Perl 5.32.1.1 and add it to PATH (vdev_setup.md #8)"
    if ($perl -and $perl -match '\\Git\\') {
        Add-PrereqResult $false "Perl (not Git's)" "first perl on PATH is Git's bundled perl: $perl" `
            "Put Strawberry Perl's perl\bin ahead of Git on PATH (vdev_setup.md #8)"
    }

    # --- Node.js 0.12.18 (mxCore/mx/CMakeLists.txt links <nodedir>\lib\x64\node.lib;
    #     smoke tests: find_package(Nodejs 0.12.18 EXACT REQUIRED)) ---------------
    $nodeFix = "Install node-v0.12.18-x64.msi, then unpack nodejs.zip into its folder (vdev_setup.md #15)"
    $node = Find-Tool "node"
    if (-not $node) {
        Add-PrereqResult $false "Node.js" "'node' not found on PATH" $nodeFix
    } else {
        $nodeDir = Split-Path $node -Parent
        $nodeVer = Get-NativeOutput $node @("--version")
        Add-PrereqResult ($nodeVer -eq "v0.12.18") "Node.js version" "first node on PATH is $nodeVer at $node (need exactly v0.12.18)" $nodeFix
        $npmCmd = Join-Path $nodeDir "npm.cmd"
        $npmVer = if (Test-Path $npmCmd) { Get-NativeOutput $npmCmd @("--version") } else { "<npm.cmd missing>" }
        Add-PrereqResult ($npmVer -eq "2.15.11") "npm version" "$npmVer (need 2.15.11, bundled with Node 0.12.18)" $nodeFix
        $nodeLib = Join-Path $nodeDir "lib\x64\node.lib"
        Add-PrereqResult (Test-Path $nodeLib) "node.lib (x64)" "$nodeLib" "Unpack nodejs.zip into $nodeDir (vdev_setup.md #15)"
        $gyp = Join-Path $nodeDir "node_modules\npm\bin\node-gyp-bin"
        Add-PrereqResult (Test-Path $gyp) "node-gyp-bin" "$gyp" $nodeFix
        $others = @(Get-Command node -All -CommandType Application -ErrorAction SilentlyContinue |
            Where-Object { (Split-Path $_.Source -Parent) -ne $nodeDir } | ForEach-Object Source)
        if ($others.Count -gt 0) { Add-PrereqWarning "Node.js" "other node.exe on PATH (shadowed): $($others -join '; ')" }
    }

    # --- Source trees ----------------------------------------------------------
    Test-SourceTrees $Cfg

    # --- Conan profile and remotes (only meaningful if conan itself is OK) ----
    if ($Cfg.ConanExe) { Test-ConanSetup $Cfg }

    return ($script:PrereqFailures.Count -eq 0)
}

# Reads the ma-sdk version from XClient's build_requires. The lookbehind keeps
# 'lzma-sdk/...' from matching.
function Get-XClientMaSdkVersion([string]$XClientSource) {
    $conanfile = Join-Path $XClientSource "conanfile.py"
    if ((Test-Path $conanfile) -and (Get-Content $conanfile -Raw) -match '(?<![\w-])ma-sdk/([^@"]+)@') {
        return $Matches[1]
    }
    return $null
}

function Test-SourceTrees($Cfg) {
    # XClient source
    $xcConan = Join-Path $Cfg.XClientSource "conanfile.py"
    $xcCMake = Join-Path $Cfg.XClientSource "CMakeLists.txt"
    $xcOk = (Test-Path $xcConan) -and (Test-Path $xcCMake) -and
            ((Get-Content $xcConan -Raw) -match 'name\s*=\s*"XClientBinaries"')
    Add-PrereqResult $xcOk "XClient source" $Cfg.XClientSource `
        "Pass -XClientSource <path to XClient checkout containing conanfile.py>"
    if ($xcOk -and -not $Cfg.MaSdkVersion) {
        Add-PrereqResult $false "XClient ma-sdk requirement" "no 'ma-sdk/<version>@' build_requires found in $xcConan" ""
    }

    # Fake MA SDK source
    $fk = $Cfg.FakeSdkSource
    $fkConan = Join-Path $fk "conanfile.py"
    $need = @("conanfile.py", "CMakeLists.txt", "src\ma_stub.cc", "src\xml_policy.cc", "include\ma\ma_client.h")
    $missing = @($need | Where-Object { -not (Test-Path (Join-Path $fk $_)) })
    Add-PrereqResult ($missing.Count -eq 0) "Fake MA SDK source" `
        "$fk$(if ($missing.Count) { ' (missing: ' + ($missing -join ', ') + ')' })" `
        "Pass -FakeSdkSource <path to a ma-sdk-fake source tree>"
    if ($missing.Count -gt 0) { return }

    $fkText = Get-Content $fkConan -Raw
    # Anchored to line start so e.g. required_conan_version = "..." doesn't match.
    $fkName = if ($fkText -match '(?m)^\s*name\s*=\s*"([^"]+)"') { $Matches[1] } else { "<none>" }
    $fkVer  = if ($fkText -match '(?m)^\s*version\s*=\s*"([^"]+)"') { $Matches[1] } else { "<none>" }
    Add-PrereqResult ($fkName -eq "ma-sdk") "Fake recipe name" "name='$fkName' (must be 'ma-sdk' to shadow the real package)" ""
    if ($Cfg.MaSdkVersion) {
        Add-PrereqResult ($fkVer -eq $Cfg.MaSdkVersion) "Fake recipe version" `
            "fake='$fkVer', XClient requires '$($Cfg.MaSdkVersion)'" `
            "Update version in $fkConan (or regenerate the fake against the SDK version XClient uses)"
    }
    $hasHooks = (Get-Content (Join-Path $fk "src\ma_stub.cc") -Raw) -match 'ma_stub_fire_start'
    Add-PrereqResult $hasHooks "Fake test hooks" "ma_stub_fire_start/stop present in src\ma_stub.cc" ""
}

function Get-ConanDataDir($Cfg) {
    $p = Get-NativeOutput $Cfg.ConanExe @("config", "get", "storage.path")
    if ($script:LastNativeExit -eq 0 -and $p -and (Test-Path $p)) { return $p }
    $home2 = Get-NativeOutput $Cfg.ConanExe @("config", "home")
    return (Join-Path $home2 "data")
}

function Get-ConanProfileSettings($Cfg) {
    $out = Get-NativeOutput $Cfg.ConanExe @("profile", "show", $Cfg.Profile)
    if ($script:LastNativeExit -ne 0) { return $null }
    $settings = @{}
    $inSettings = $false
    foreach ($l in ($out -split "`r?`n")) {
        if ($l -match '^\[(.+)\]') { $inSettings = ($Matches[1] -eq "settings"); continue }
        if ($inSettings -and $l -match '^\s*([^=\s]+)\s*=\s*(.+?)\s*$') { $settings[$Matches[1]] = $Matches[2] }
    }
    return $settings
}

function Test-ConanSetup($Cfg) {
    # Profile: the fake's package_id is settings-derived, so the profile must
    # match what XClient builds with or XClient silently ignores the fake.
    $want = [ordered]@{
        "os" = "Windows"; "arch" = "x86_64"; "compiler" = "Visual Studio"; "compiler.version" = "17"
        "compiler.runtime" = "MD"; "compiler.toolset" = "v143"; "compiler.cppstd" = "20"; "build_type" = "RelWithDebInfo"
    }
    $s = Get-ConanProfileSettings $Cfg
    if ($null -eq $s) {
        Add-PrereqResult $false "Conan profile" "'$($Cfg.Profile)' not found (conan profile list)" `
            "conan config install http://artifactory.eng.fireeye.com/Unified-Build/conan/conan_config_trellix_unified_v2.2.zip (vdev_setup.md #14)"
    } else {
        $bad = @($want.Keys | Where-Object { $s[$_] -ne $want[$_] } | ForEach-Object { "$_=$($s[$_]) (want $($want[$_]))" })
        Add-PrereqResult ($bad.Count -eq 0) "Conan profile" `
            "$($Cfg.Profile)$(if ($bad.Count) { ': ' + ($bad -join ', ') } else { ' settings match' })" `
            "Fix the profile (conan profile show $($Cfg.Profile)) or pass -ConanProfile <name>"
    }

    # Remotes: at least one must answer so missing packages can be pulled.
    $remotes = @((Get-NativeOutput $Cfg.ConanExe @("remote", "list")) -split "`r?`n" |
        Where-Object { $_ -match '^([^:\s]+):\s+http' } | ForEach-Object { ($_ -split ':')[0] })
    if ($remotes.Count -eq 0) {
        Add-PrereqResult $false "Conan remotes" "none configured" "conan config install <trellix conan config zip> (vdev_setup.md #14)"
    } elseif ($Cfg.SkipRemoteCheck) {
        Add-PrereqWarning "Conan remotes" "reachability check skipped (-SkipRemoteCheck); configured: $($remotes -join ', ')"
    } else {
        $reachable = @()
        foreach ($r in $remotes) {
            # A pattern search exits 0 on a reachable remote even with no
            # matches, non-zero if unreachable/unauthorised.
            Get-NativeOutput $Cfg.ConanExe @("search", "ma-sdk*", "-r", $r) | Out-Null
            if ($script:LastNativeExit -eq 0) { $reachable += $r }
            else { Add-PrereqWarning "Conan remote '$r'" "not reachable or needs login (conan user -r $r -p <password> <user>)" }
        }
        Add-PrereqResult ($reachable.Count -gt 0) "Conan remotes" `
            "reachable: $(if ($reachable.Count) { $reachable -join ', ' } else { 'none' }) of $($remotes -join ', ')" `
            "Check VPN/network, or log in: conan user -r <remote> -p <password> <user>"
    }

    # Informational: compare the fake's headers to the real package if the real
    # one is still in the cache (the fake is meant to ship them verbatim).
    $dataDir = Get-ConanDataDir $Cfg
    $Cfg.ConanDataDir = $dataDir
    $pkgRoot = Join-Path $dataDir ($Cfg.MaSdkRealRef -replace '@', '/' -replace '/', '\')
    $realInc = Get-ChildItem (Join-Path $pkgRoot "package") -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "include" } | Where-Object { Test-Path $_ } | Select-Object -First 1
    $realLib = if ($realInc) { Join-Path (Split-Path $realInc -Parent) "lib\ma.lib" } else { $null }
    if ($realInc -and -not (Test-BinaryContains $realLib "ma_stub_fire_start")) {
        $d = Compare-HeaderTree (Join-Path $Cfg.FakeSdkSource "include") $realInc
        if ($d.Count -eq 0) { Write-Ok "Fake headers - identical to cached real $($Cfg.MaSdkRealRef) (ignoring CRLF)" }
        else { Add-PrereqWarning "Fake headers" "$($d.Count) header(s) differ from real package, e.g. $($d[0])" }
    }
}
