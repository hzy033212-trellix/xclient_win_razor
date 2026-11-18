# Stages 1-5 and final verification.

# Marker string that only the fake's ma.lib contains (test hook symbol name).
$script:FakeLibMarker = "ma_stub_fire_start"
# Marker the fake compiles into whatever links it (its log file name).
$script:FakeLinkMarker = "ma_stub.log"

function Get-MaSdkCacheRoot($Cfg) {
    return Join-Path $Cfg.ConanDataDir ($Cfg.MaSdkRealRef -replace '@', '/' -replace '/', '\')
}

function Invoke-ConanInstall($Cfg, [string]$LogName) {
    Invoke-Step $Cfg.ConanExe @("install", $Cfg.XClientSource, $Cfg.XClientUserChannel,
        "-pr", $Cfg.Profile, "-if", $Cfg.BuildDir, "--build=missing") $LogName $Cfg.BuildDir `
        "conan install of XClient dependencies failed"
}

# --- Stage 1: Conan setup ------------------------------------------------------
function Invoke-ConanSetup($Cfg) {
    Write-Banner "Stage 1/5 - Conan setup"
    Write-Info "Conan home        : $(Get-NativeOutput $Cfg.ConanExe @('config', 'home'))"
    Write-Info "Conan data dir    : $($Cfg.ConanDataDir)"
    Write-Info "Profile           : $($Cfg.Profile)"
    Write-Info "XClient reference : XClientBinaries@$($Cfg.XClientUserChannel)"
    Write-Info "ma-sdk reference  : $($Cfg.MaSdkRealRef)  (fake is created under this same ref)"
    Write-Info "Build dir         : $($Cfg.BuildDir)"
    Write-Warn2 "The Conan cache is shared per user: after stage 3 every XClient build on this"
    Write-Warn2 "account that resolves $($Cfg.MaSdkRealRef) links the FAKE until you restore it."
    Import-VsDevEnv $Cfg.VsPath
    New-Item -ItemType Directory -Force -Path $Cfg.BuildDir | Out-Null
}

# --- Stage 2: pull packages ------------------------------------------------------
function Invoke-PullPackages($Cfg) {
    Write-Banner "Stage 2/5 - Pull XClient dependency packages"
    Invoke-ConanInstall $Cfg "02-conan-install.log"
    Write-Ok "All XClient build requirements resolved into the local cache"
}

# --- Stage 3: replace ma-sdk with the fake -------------------------------------
function Invoke-FakeSelfTests($Cfg) {
    $fk = $Cfg.FakeSdkSource
    $work = Join-Path $Cfg.BuildDir "fake-sdk-selftest"
    if (Test-Path $work) { Remove-Item -Recurse -Force $work }
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    Write-Info "Running the fake's standalone tests in $work"

    Invoke-Step "cl" @("/nologo", "/EHsc", "/I", "$fk\src", "$fk\test\xml_selftest.cc", "$fk\src\xml_policy.cc",
        "/Fe:xml_selftest.exe") "03a-selftest-xml-build.log" $work "failed to compile the fake's xml_selftest"
    Test-SelfTestRun "xml_selftest.exe" @() "ALL PASS" "03b-selftest-xml-run.log" $work

    Invoke-Step "cmake" @("-S", $fk, "-B", "$work\cmake", "-A", "x64") "03c-selftest-lib-configure.log" $work `
        "failed to configure the fake's ma.lib"
    Invoke-Step "cmake" @("--build", "$work\cmake", "--config", "RelWithDebInfo") "03d-selftest-lib-build.log" $work `
        "failed to compile the fake's ma.lib (ma_stub.cc / xml_policy.cc)"
    $lib = "$work\cmake\RelWithDebInfo\ma.lib"

    Invoke-Step "cl" @("/nologo", "/EHsc", "/MD", "/I", "$fk\include", "$fk\test\abi_driver.cc", $lib,
        "/Fe:abi_driver.exe") "03e-selftest-abi-build.log" $work "failed to compile the fake's abi_driver"
    Test-SelfTestRun "abi_driver.exe" @("$fk\sample\ma_stub_policy.xml") "ABI OK" "03f-selftest-abi-run.log" $work

    Invoke-Step "cl" @("/nologo", "/EHsc", "/MD", "/I", "$fk\include", "$fk\test\capture_driver.cc", $lib,
        "/Fe:capture_driver.exe") "03g-selftest-capture-build.log" $work "failed to compile the fake's capture_driver"
    Test-SelfTestRun "capture_driver.exe" @() "ALL PASS" "03h-selftest-capture-run.log" $work
}

function Test-SelfTestRun([string]$Exe, [string[]]$ArgList, [string]$Expect, [string]$LogName, [string]$WorkDir) {
    $code = Invoke-Native -Exe (Join-Path $WorkDir $Exe) -ArgList $ArgList -WorkDir $WorkDir -LogName $LogName
    $log = Join-Path $script:LogDir $LogName
    $passed = ($code -eq 0) -and ((Get-Content $log -Raw) -match [regex]::Escape($Expect))
    if (-not $passed) { Stop-Build "fake self-test $Exe did not report '$Expect' (exit $code, see $log)" }
    Write-Ok "fake self-test $Exe -> $Expect"
}

function Invoke-ReplaceMaSdk($Cfg) {
    Write-Banner "Stage 3/5 - Replace ma-sdk with the fake MA SDK"
    $ref = $Cfg.MaSdkRealRef
    $cacheRoot = Get-MaSdkCacheRoot $Cfg

    # 3.1 Self-test the fake before touching the cache.
    if ($Cfg.SkipFakeTests) { Write-Warn2 "Skipping the fake's self-tests (-SkipFakeTests)" }
    else { Invoke-FakeSelfTests $Cfg }

    # 3.2 Remove whatever ma-sdk (real or a previous fake) is cached so no stale
    #     binary or recipe is reused.
    if (Test-Path $cacheRoot) {
        Invoke-Step $Cfg.ConanExe @("remove", $ref, "-f") "03i-conan-remove-ma-sdk.log" $Cfg.BuildDir `
            "conan remove $ref failed"
        Write-Ok "Removed cached $ref"
    } else {
        Write-Info "$ref not in cache; nothing to remove"
    }

    # 3.3 conan create = export + build + package (export alone would not build ma.lib).
    Invoke-Step $Cfg.ConanExe @("create", $Cfg.FakeSdkSource, $ref, "-pr", $Cfg.Profile) `
        "03j-conan-create-fake.log" $Cfg.BuildDir "conan create of the fake MA SDK failed"

    $fakeLib = Get-ChildItem (Join-Path $cacheRoot "package") -Recurse -Filter ma.lib -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $fakeLib -or -not (Test-BinaryContains $fakeLib.FullName $script:FakeLibMarker)) {
        Stop-Build "cached $ref has no fake ma.lib after conan create (looked under $cacheRoot\package)"
    }
    Write-Ok "Fake ma.lib cached: $($fakeLib.FullName) ($($fakeLib.Length) bytes)"

    # 3.4 Re-resolve XClient (no --update, which would re-pull the real SDK) and
    #     prove the generated build info points at the fake.
    Invoke-ConanInstall $Cfg "03k-conan-install-with-fake.log"
    $bi = Get-Content (Join-Path $Cfg.BuildDir "conanbuildinfo.txt")
    $i = [array]::IndexOf($bi, "[rootpath_ma-sdk]")
    if ($i -lt 0) { Stop-Build "conanbuildinfo.txt has no [rootpath_ma-sdk] section" }
    $resolved = $bi[$i + 1].Trim()
    if (-not (Test-BinaryContains (Join-Path $resolved "lib\ma.lib") $script:FakeLibMarker)) {
        Stop-Build "XClient resolves ma-sdk to $resolved, which is not the fake (profile/package_id mismatch?)"
    }
    Write-Ok "XClient now resolves ma-sdk -> $resolved (fake)"
}

# --- Stage 4: configure ----------------------------------------------------------
function Invoke-Configure($Cfg) {
    Write-Banner "Stage 4/5 - Configure XClient (CMake via conan build --configure)"
    Invoke-Step $Cfg.ConanExe @("build", "-bf", $Cfg.BuildDir, "-sf", $Cfg.XClientSource, $Cfg.XClientSource,
        "--configure") "04-configure.log" $Cfg.BuildDir "XClient CMake configure failed"
    # The VS generator takes the newest installed SDK unless CMAKE_SYSTEM_VERSION (from
    # CONAN_CMAKE_SYSTEM_VERSION, Import-VsDevEnv) names one; a build tree configured before
    # keeps the SDK it was configured with.
    $proj = Join-Path $Cfg.BuildDir "ZERO_CHECK.vcxproj"
    if (-not (Test-Path $proj)) { Stop-Build "configure made no $proj to read the Windows SDK from" }
    $sdk = Select-String -Path $proj -Pattern '<WindowsTargetPlatformVersion>([^<]*)<' |
        Select-Object -First 1 | ForEach-Object { $_.Matches[0].Groups[1].Value }
    if ($sdk -ne $script:WinSdkVersion) {
        Stop-Build "CMake selected Windows SDK '$sdk', not $script:WinSdkVersion (a build tree configured before? delete $($Cfg.BuildDir) and re-run)"
    }
    Write-Ok "Windows SDK: $sdk"

    if ($Cfg.EnableFakeUnitTests) {
        # mxServices/test/unit/CMakeLists.txt: OPTION_MA_LIVE_TESTS builds the real-MAClient
        # suite; OPTION_MA_SDK_FAKE adds the [FAKE-ONLY] tests calling ma_stub_fire_*.
        Invoke-Step "cmake" @("-DOPTION_MA_LIVE_TESTS=ON", "-DOPTION_MA_SDK_FAKE=ON", $Cfg.BuildDir) `
            "04b-configure-fake-tests.log" $Cfg.BuildDir "enabling OPTION_MA_LIVE_TESTS/OPTION_MA_SDK_FAKE failed"
        Write-Ok "Enabled OPTION_MA_LIVE_TESTS=ON, OPTION_MA_SDK_FAKE=ON (mxservices_unit_test)"
    }
    Write-Ok "Configure succeeded"
}

# --- Stage 5: compile --------------------------------------------------------------
function Invoke-Compile($Cfg) {
    Write-Banner "Stage 5/5 - Compile XClient (conan build --build)"
    $code = Invoke-Native -Exe $Cfg.ConanExe -ArgList @("build", "-bf", $Cfg.BuildDir, "-sf", $Cfg.XClientSource,
        $Cfg.XClientSource, "--build") -WorkDir $Cfg.BuildDir -LogName "05-compile.log"
    if ($code -ne 0) {
        $log = Join-Path $script:LogDir "05-compile.log"
        Write-Host ""
        Write-Fail "Compile failed. First distinct errors:"
        Select-String -Path $log -Pattern ': error |: fatal error |error MSB|CUSTOMBUILD : error' |
            ForEach-Object { $_.Line.Trim() } | Select-Object -Unique -First 15 | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        Stop-Build "XClient compile failed (exit $code, full log: $log)"
    }
    Write-Ok "Compile succeeded"
}

# --- Verification ----------------------------------------------------------------
function Invoke-Verify($Cfg) {
    Write-Banner "Verify"
    $bin = Join-Path $Cfg.BuildDir "install\bin"
    $xc = Join-Path $bin "xclient.exe"
    $agent = Join-Path $bin "mxAgent.dll"
    $problems = @()

    if (Test-Path $xc) { Write-Ok "xclient.exe   : $xc ($((Get-Item $xc).LastWriteTime))" }
    else { $problems += "xclient.exe not found at $xc" }

    # mxAgent.dll statically links ma (mxAgent/mxa/CMakeLists.txt: CONAN_PKG::ma-sdk).
    if (Test-BinaryContains $agent $script:FakeLinkMarker) { Write-Ok "mxAgent.dll   : contains '$($script:FakeLinkMarker)' -> linked against the FAKE MA SDK" }
    else { $problems += "mxAgent.dll at $agent does not contain '$($script:FakeLinkMarker)' (not linked against the fake?)" }

    $failed = @(Get-ChildItem $Cfg.BuildDir -Recurse -Filter unsuccessfulbuild -ErrorAction SilentlyContinue)
    if ($failed.Count -eq 0) { Write-Ok "MSBuild       : no unsuccessfulbuild markers" }
    else { $problems += "MSBuild left $($failed.Count) unsuccessfulbuild marker(s), e.g. $($failed[0].FullName)" }

    if ($problems.Count -gt 0) {
        $problems | ForEach-Object { Write-Fail $_ }
        Stop-Build "verification failed"
    }
}

function Write-Summary($Cfg) {
    Write-Banner "DONE - XClient built against the fake MA SDK"
    Write-Info "Binaries : $(Join-Path $Cfg.BuildDir 'install\bin')"
    Write-Info "Logs     : $script:LogDir"
    Write-Info ""
    Write-Info "Runtime: put an ePO policy XML at %ProgramData%\Trellix\XClient\ma_stub_policy.xml"
    Write-Info "(or set MA_STUB_POLICY_FILE for console runs). ma_stub.log next to it proves the fake is loaded."
    Write-Info "See $($Cfg.FakeSdkSource)\README.md, 'Feeding policy'."
    Write-Info ""
    Write-Warn2 "To restore the REAL ma-sdk for other builds on this account:"
    Write-Info "  conan remove `"$($Cfg.MaSdkRealRef)`" -f"
    Write-Info "  then re-run 'conan install' for that XClient build (it re-fetches the vendor package)."
}
