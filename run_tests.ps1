<#
.SYNOPSIS
    Installs an XClient msi without MA, provisions it with HXSim, runs the tests, and uninstalls it.

.DESCRIPTION
    1. Pre-flight (nothing is changed if it fails): admin, no MA, no XClient, Artifactory credentials.
    2. Add the fake Agent registry key (fake_ma_key.ps1 -Enable) and seed the stub policy
       (self-protection off) into %ProgramData%\Trellix\XClient.
    3. msiexec /i the msi; check XClient's SERVICE runs and MA is still absent.
    4. pytest: HXSim provisioning once (fresh PKI, stub policy, enrollment, intel key, IOC feed,
       alerting live), then the tests group by group, one XClient config per group, with each
       group's audits run as one batch of HXSim tasks (tests/util/audit_batch.py).
    5. Always, pass or fail: stop HXSim, uninstall XClient (while the key still exists - the msi's
       precheck also runs on uninstall), delete the stub policy, remove the fake key, and verify
       the host is back to "no MA key, no XClient".

    With -WithMA (the Orbit msi), steps 2 and 5 install / uninstall MA instead, and HXSim
    provisioning swaps in the fake-MA build's binaries first, as win_razor did.

    With -KeepInstalled, step 5 leaves XClient (and MA / the fake key) installed and HXSim
    running, and records them in install\kept_install.json. The next run with the same msi and
    mode reuses them: steps 2-3 and HXSim provisioning are skipped, and no reboot is needed in
    between. Without -KeepInstalled that run cleans everything up at the end as usual;
    -Cleanup only cleans up a kept install.

    Works the same for the fake-MA msi (tools\fakema\Get-FakeMaMsi.ps1) and the Orbit msi it was patched
    from, so their results can be compared (compare_results.py).

    Logs and results go to logs\<timestamp>_<label>\ (run.log, install.log, junit.xml, pytest.log,
    memory.csv = host and per-process memory every 30 s (mem_monitor.ps1), results\ = the
    per-test audit outputs). Exit code: 0 passed, 1 failed, 2 pre-flight refused.

.PARAMETER Msi
    The XClient msi to install. Default: the fake-MA msi of -Version (the Orbit msi with -WithMA),
    made by tools\fakema\Get-FakeMaMsi.ps1, which builds the fake-MA mxAgent.dll only if that
    version's XClient commit differs from the last build.

.PARAMETER Version
    Without -Msi: 'latest' (default: the newest passed Orbit build) or a version like 50.4.0.174.

.PARAMETER Label
    Name for the log folder. Default: the msi file name without extension.

.PARAMETER WithMA
    For the Orbit msi, whose mxAgent.dll takes policy only from MA. As win_razor did:
    install MA (FramePkg_UPD.exe) instead of the fake key; HXSim provisioning turns
    XClient's self-protection off through MA (local_policy_config), swaps in the
    fake-MA build's mxAgent.dll, mxCore.dll and xclient.exe (-FakeMaBin), and then
    uses the stub policy as without MA. MA is uninstalled at cleanup.

.PARAMETER FakeMaBin
    With -WithMA: folder holding the fake-MA build's mxAgent.dll, mxCore.dll and
    xclient.exe. Default: this repo's fake-MA build (NWR_ROOT\fakema\build\install\bin, made by
    tools\fakema\Get-FakeMaMsi.ps1). Pre-flight refuses it if its last_build.json names another
    XClient commit than the msi's.

.PARAMETER KeepInstalled
    Leave XClient installed and HXSim running at the end (only if the install succeeded), for the
    next run of the same msi. For development runs; compare msi on fresh installs.

.PARAMETER Cleanup
    Clean up a kept install (install\kept_install.json) and exit, running no tests. -Msi is not
    needed.

.PARAMETER Tests
    pytest arguments selecting the tests, as an array or one comma-separated string.
    Default: tests (all of them). Pre-flight refuses if they select no test.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File run_tests.ps1
    (the latest passed XClient: its fake-MA msi, built or reused, then all tests)
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File run_tests.ps1 -Msi C:\msi\xclient_fakema_50.4.0.174_x64.msi
#>
[CmdletBinding()]
param(
    [string]$Msi,
    [string]$Version = 'latest',
    [string]$Label,
    [switch]$WithMA,
    [switch]$KeepInstalled,
    [switch]$Cleanup,
    [string]$FakeMaBin,
    [string[]]$Tests = @('tests')
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$keyTool = Join-Path $repoDir 'fake_ma_key.ps1'
$python  = Join-Path $repoDir 'venv\Scripts\python.exe'
# What -KeepInstalled left installed (msi, version, upgrade code, mode), for the next run.
$keptFile = Join-Path $repoDir 'install\kept_install.json'
# This repo's tools (setup.ps1) first on PATH: git, Git Bash, Python.
. (Join-Path $repoDir 'tools\toolchain.ps1')
Use-Toolchain
if (-not $FakeMaBin) { $FakeMaBin = Join-Path $FakeMaWork 'build\install\bin' }

function Write-Step([string]$Message) { Write-Host ''; Write-Host "=== $Message" -ForegroundColor Cyan }

$installer = New-Object -ComObject WindowsInstaller.Installer
function Get-MsiProperty([string]$Path, [string]$Name) {
    $db = $installer.GetType().InvokeMember('OpenDatabase', 'InvokeMethod', $null, $installer, @($Path, 0))
    $view = $db.GetType().InvokeMember('OpenView', 'InvokeMethod', $null, $db, @("SELECT ``Value`` FROM ``Property`` WHERE ``Property``='$Name'"))
    $view.GetType().InvokeMember('Execute', 'InvokeMethod', $null, $view, $null) | Out-Null
    $rec = $view.GetType().InvokeMember('Fetch', 'InvokeMethod', $null, $view, $null)
    $value = $rec.GetType().InvokeMember('StringData', 'GetProperty', $null, $rec, @(1))
    $view.GetType().InvokeMember('Close', 'InvokeMethod', $null, $view, $null) | Out-Null
    $value
}
# Product codes of installed products sharing the msi's UpgradeCode (any XClient build).
function Get-InstalledXClient([string]$UpgradeCode) {
    @($installer.GetType().InvokeMember('RelatedProducts', 'GetProperty', $null, $installer, @($UpgradeCode)))
}
function Get-XClientModes {
    @(Get-CimInstance Win32_Process -Filter "Name='xclient.exe'" | ForEach-Object {
        if ($_.CommandLine -match '--mode\s+(\w+)') { $Matches[1] }
    })
}
function Invoke-Msiexec([string]$Arguments, [string]$Log) {
    $p = Start-Process msiexec.exe -ArgumentList "$Arguments /qn /l*v `"$Log`"" -Wait -PassThru
    $p.ExitCode
}
function Invoke-RepoPython([string]$Code) {
    Push-Location $repoDir
    try { & $python -c $Code 2>&1 | ForEach-Object { "$_" } } finally { Pop-Location }
}

$kept = if (Test-Path $keptFile) { Get-Content $keptFile -Raw | ConvertFrom-Json } else { $null }
if ($Cleanup) {
    if (-not $kept) { Write-Host "Nothing to clean up: no $keptFile" -ForegroundColor Yellow; exit 0 }
    $WithMA = [bool]$kept.withMA
    if (-not $Label) { $Label = 'cleanup' }
} else {
    if (-not $Msi) {
        # The msi of -Version (default latest), made ready by Get-FakeMaMsi.ps1.
        Write-Host "No -Msi: getting the msi of XClient '$Version' (tools\fakema\Get-FakeMaMsi.ps1)" -ForegroundColor Cyan
        $lines = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoDir 'tools\fakema\Get-FakeMaMsi.ps1') -Version $Version |
                 ForEach-Object { Write-Host $_; $_ }
        if ($LASTEXITCODE -ne 0) { Write-Host "Get-FakeMaMsi.ps1 failed ($LASTEXITCODE)" -ForegroundColor Red; exit 2 }
        $got = @{}
        foreach ($l in $lines) { if ("$l" -match '^(VERSION|ORBIT_MSI|FAKEMA_MSI|FAKEMA_BIN)=(.+)$') { $got[$Matches[1]] = $Matches[2] } }
        $Msi = if ($WithMA) { $got.ORBIT_MSI } else { $got.FAKEMA_MSI }
        if ($WithMA -and $got.FAKEMA_BIN) { $FakeMaBin = $got.FAKEMA_BIN }
        if (-not $Msi) { Write-Host 'Get-FakeMaMsi.ps1 reported no msi' -ForegroundColor Red; exit 2 }
    }
    if (-not (Test-Path $Msi)) { Write-Host "msi not found: $Msi" -ForegroundColor Red; exit 2 }
    $Msi = (Resolve-Path $Msi).Path
    if (-not $Label) { $Label = [IO.Path]::GetFileNameWithoutExtension($Msi) }
}
$logDir = Join-Path $repoDir ("logs\" + (Get-Date).ToString('yyyyMMdd_HHmmss') + "_$Label")
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Transcript -Path (Join-Path $logDir 'run.log') | Out-Null

function Fail-Preflight([string]$Message) {
    Write-Host "PRE-FLIGHT REFUSED: $Message" -ForegroundColor Red
    Stop-Transcript | Out-Null
    exit 2
}

# ---------------------------------------------------------------------------
# 1. Pre-flight
# ---------------------------------------------------------------------------
$reuse = $false
if ($Cleanup) {
    $upgradeCode = $kept.upgradeCode
    $cmdagent = Join-Path $env:ProgramFiles 'McAfee\Agent\cmdagent.exe'
    $failures = New-Object System.Collections.Generic.List[string]
} else {
    Write-Step '1. Pre-flight'
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail-Preflight 'run as Administrator.' }
    if (-not (Test-Path $python)) { Fail-Preflight "venv missing: $python (see README.md)" }

    $version     = Get-MsiProperty $Msi 'ProductVersion'
    $upgradeCode = Get-MsiProperty $Msi 'UpgradeCode'

    $cmdagent = Join-Path $env:ProgramFiles 'McAfee\Agent\cmdagent.exe'
    $installed = Get-InstalledXClient $upgradeCode
    # Reuse what an earlier -KeepInstalled run left: the same msi, version and mode, still installed.
    if ($installed.Count -and $kept -and $kept.msi -eq $Msi -and $kept.version -eq $version -and
        [bool]$kept.withMA -eq [bool]$WithMA -and ($WithMA -or (Test-Path 'HKLM:\SOFTWARE\WOW6432Node\McAfee\Agent'))) {
        $reuse = $true
        Write-Host "Reusing the install kept by an earlier -KeepInstalled run ($keptFile, $($kept.keptAt))" -ForegroundColor Yellow
    }
    if ($installed.Count -and -not $reuse) {
        Fail-Preflight "XClient is already installed ($($installed -join ', ')) and is not a kept install of this msi; uninstall it first (or run with -Cleanup)."
    }
    if (-not $reuse -and (Test-Path $cmdagent)) { Fail-Preflight "MA is installed ($cmdagent); uninstall it first - the tests run XClient without MA." }
    if (Test-Path 'HKLM:\SOFTWARE\WOW6432Node\McAfee\Agent') {
        if ($null -eq (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\McAfee\Agent' -Name FakeForXClient -ErrorAction SilentlyContinue)) {
            Fail-Preflight 'a real MA registry key exists (HKLM\SOFTWARE\WOW6432Node\McAfee\Agent).'
        }
        Write-Warning 'A fake MA key from an earlier run is present; it will be reused and removed at the end.'
    }
    # The vscore driver installer refuses to run ("Reboot required", msi error 1603) while the drivers
    # of an earlier uninstall are still waiting to be deleted at boot.
    $pending = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations
    if (-not $reuse -and ($pending | Where-Object { $_ -match '\\drivers\\mfe|McAfee|Trellix' })) {
        Fail-Preflight 'a reboot is pending from an earlier XClient uninstall (vscore drivers to delete); reboot first.'
    }
    if (-not $env:ARTIFACTORY_USER -or -not $env:ARTIFACTORY_TOKEN) { Fail-Preflight 'set ARTIFACTORY_USER and ARTIFACTORY_TOKEN (HXSim source lookup, mmsutil.exe).' }
    if ($WithMA) {
        foreach ($f in 'mxAgent.dll', 'mxCore.dll', 'xclient.exe') {
            if (-not (Test-Path (Join-Path $FakeMaBin $f))) { Fail-Preflight "-FakeMaBin $FakeMaBin has no $f" }
        }
        if (-not [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes((Join-Path $FakeMaBin 'mxAgent.dll'))).Contains('ma_stub.log')) {
            Fail-Preflight "$FakeMaBin\mxAgent.dll is not linked against the fake MA"
        }
        # The fake-MA build must be of the commit the msi was built from (its binaries carry no
        # build number): <build root>\last_build.json, written by the fake-MA build, names it.
        $lastBuild = Join-Path (Split-Path (Split-Path (Split-Path $FakeMaBin))) 'last_build.json'
        if (-not (Test-Path $lastBuild)) { Fail-Preflight "no ${lastBuild}: can't tell which XClient commit -FakeMaBin was built from" }
        $fakeCommit = (Get-Content $lastBuild -Raw | ConvertFrom-Json).XClient
        $env:XCLIENT_VERSION = $version
        $msiCommit = (Invoke-RepoPython "from tests.util import artifactory; print(artifactory.xclient_source()[1])" | Select-Object -Last 1).Trim()
        if ($fakeCommit -ne $msiCommit) {
            Fail-Preflight "-FakeMaBin was built from XClient $fakeCommit, the msi from $msiCommit; build it with tools\fakema\Get-FakeMaMsi.ps1 -Version $version"
        }
        Write-Host "Fake-MA   : $FakeMaBin (XClient $fakeCommit, as the msi)"
    }
    # -Tests may arrive as one comma-separated string (powershell -File doesn't build arrays).
    $Tests = @($Tests -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    Push-Location $repoDir
    try { $collected = & $python -m pytest --collect-only -q -p no:cacheprovider @Tests 2>&1 | Select-String '::' } finally { Pop-Location }
    if (-not $collected) { Fail-Preflight "no tests collected for -Tests $($Tests -join ' ')" }
    Write-Host "Tests      : $(@($collected).Count) collected from $($Tests -join ' ')"

    Write-Host "Msi        : $Msi"
    Write-Host "Version    : $version (XCLIENT_VERSION)"
    Write-Host "Signature  : $((Get-AuthenticodeSignature $Msi).SignerCertificate.Subject)"
    Write-Host "Logs       : $logDir"

    $failures = New-Object System.Collections.Generic.List[string]
}
# Memory every 30 s into memory.csv; the monitor stops by itself when this script exits.
Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', "`"$(Join-Path $repoDir 'mem_monitor.ps1')`"", '-Csv', "`"$logDir\memory.csv`"",
    '-ParentPid', $PID, '-PytestLog', "`"$logDir\pytest.log`"") | Out-Null
Write-Host "Memory     : $logDir\memory.csv"
# Defender exclusions for what the run writes in bulk (every HXSim upload, every audit output) and
# HXSim's node process: less scanning, CPU and memory during uploads. Added only if missing; a
# host that doesn't allow it (e.g. centrally managed Defender) just runs without them.
function Add-DefenderExclusions {
    $node = [Environment]::ExpandEnvironmentVariables((Get-Content (Join-Path $repoDir 'paths.json') -Raw | ConvertFrom-Json).node_exe)
    $wanted = @{ ExclusionPath = @((Join-Path $repoDir 'install\hxsim\rundir'), (Join-Path $repoDir 'temp'))
                 ExclusionProcess = @($node) }
    try {
        $pref = Get-MpPreference
    } catch {
        Write-Host "Defender exclusions not checked (Get-MpPreference: $($_.Exception.Message)); running without them" -ForegroundColor Yellow
        return
    }
    foreach ($kind in 'ExclusionPath', 'ExclusionProcess') {
        foreach ($item in $wanted[$kind]) {
            if (@($pref.$kind) -contains $item) { continue }
            try {
                $splat = @{ $kind = $item; ErrorAction = 'Stop' }
                Add-MpPreference @splat
                Write-Host "Defender exclusion added ($kind): $item"
            } catch {
                Write-Host "Defender exclusion not added ($kind $item): $($_.Exception.Message); running without it" -ForegroundColor Yellow
            }
        }
    }
}
if (-not $Cleanup) { Add-DefenderExclusions }

$installedOk = $false
try {
    if ($Cleanup) { throw [System.OperationCanceledException]::new('cleanup only') }
    # -----------------------------------------------------------------------
    # 2. Fake Agent key (or MA with -WithMA)
    # -----------------------------------------------------------------------
    $env:XCLIENT_VERSION = $version
    $env:XCLIENT_WITH_MA = if ($WithMA) { '1' } else { '0' }
    $env:XCLIENT_FAKE_MA_BIN = $FakeMaBin
    # Read by conftest.py: reuse the running HXSim / leave it running at the end.
    $env:XCLIENT_REUSE = if ($reuse) { '1' } else { '0' }
    $env:XCLIENT_KEEP = if ($KeepInstalled) { '1' } else { '0' }
    if ($reuse) {
        Write-Step '2-3. Kept install reused (no install)'
        $modes = Get-XClientModes
        Write-Host "xclient.exe modes running: $($modes -join ', ')"
        if ($modes -notcontains 'SERVICE') { throw 'The kept XClient SERVICE is not running; run -Cleanup and start over.' }
    } elseif ($WithMA) {
        Write-Step '2. Install MA (-WithMA)'
        Invoke-RepoPython "from tests.util import artifactory; artifactory.ensure_ma_tools(); print('MA tools staged')"
        $framePkg = Join-Path $repoDir 'install\FramePkg_UPD.exe'
        if (-not (Test-Path $framePkg)) { throw "MA tools not staged: $framePkg" }
        $p = Start-Process $framePkg -ArgumentList '/install=agent', '/Silent' -Wait -PassThru
        Write-Host "FramePkg_UPD.exe exit code: $($p.ExitCode)"
        $deadline = (Get-Date).AddSeconds(300)
        while (-not (Test-Path $cmdagent) -and (Get-Date) -lt $deadline) { Start-Sleep 5 }
        if (-not (Test-Path $cmdagent)) { throw "MA did not install ($cmdagent missing)" }
        Write-Host "MA installed: $cmdagent"
    } else {
        Write-Step '2. Add the fake MA registry key'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $keyTool -Enable
        if ($LASTEXITCODE -ne 0) { throw "fake_ma_key.ps1 -Enable failed ($LASTEXITCODE)" }

        # Seed the key-less stub policy before the install. With no MA, this file is the only policy
        # source, and XClient's self-protection would otherwise lock it (and its folder) so HXSim
        # provisioning couldn't drop its PKI-pinned version. The template turns protection off.
        $stubTemplate = Join-Path $repoDir 'install\ma_stub_policy.xml'
        if (-not (Select-String -Path $stubTemplate -SimpleMatch '"mxa/process/protection_enabled" value="false"' -Quiet)) {
            throw "$stubTemplate doesn't set mxa/process/protection_enabled=false"
        }
        $stubDir = Join-Path $env:ProgramData 'Trellix\XClient'
        New-Item -ItemType Directory -Force -Path $stubDir | Out-Null
        Copy-Item $stubTemplate (Join-Path $stubDir 'ma_stub_policy.xml') -Force
        Write-Host "Seeded $stubDir\ma_stub_policy.xml (self-protection off)"
    }

    # -----------------------------------------------------------------------
    # 3. Install without MA
    # -----------------------------------------------------------------------
    if (-not $reuse) {
        Write-Step $(if ($WithMA) { '3. Install the msi (with MA)' } else { '3. Install the msi (no MA on the host)' })
        $rc = Invoke-Msiexec "/i `"$Msi`"" (Join-Path $logDir 'install.log')
        Write-Host "msiexec /i exit code: $rc"
        if ($rc -ne 0 -and $rc -ne 3010) { throw "msi install failed ($rc); see $logDir\install.log" }
        if (-not $WithMA -and (Test-Path $cmdagent)) { throw 'MA appeared after the install; expected none.' }

        $deadline = (Get-Date).AddSeconds(180)
        # Only SERVICE until a policy enables Eventor: the stub policy HXSim provisioning drops.
        do { Start-Sleep 5; $modes = Get-XClientModes } until ($modes -contains 'SERVICE' -or (Get-Date) -gt $deadline)
        Write-Host "xclient.exe modes running: $($modes -join ', ')"
        if ($modes -notcontains 'SERVICE') { throw 'XClient SERVICE did not start after install.' }
        $agentDll = Join-Path $env:ProgramFiles 'Trellix\XClient\mxAgent.dll'
        try {
            $fake = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($agentDll)).Contains('ma_stub.log')
            Write-Host "Installed mxAgent.dll linked against the fake MA: $fake"
        } catch [UnauthorizedAccessException] { Write-Warning "Can't read $agentDll (self-protection)." }
    }
    $installedOk = $true

    # -----------------------------------------------------------------------
    # 4. HXSim provisioning + tests
    # -----------------------------------------------------------------------
    Write-Step '4. pytest: HXSim provisioning, then the tests group by group'
    $resultsDir = Join-Path $repoDir 'temp'
    if (Test-Path $resultsDir) {
        # A reused install keeps temp\hxsim (its PKI, stub policy and ready marker).
        Get-ChildItem $resultsDir | Where-Object { -not ($reuse -and $_.Name -eq 'hxsim') } | Remove-Item -Recurse -Force
    }
    $pytestArgs = @('-m', 'pytest', '-p', 'no:cacheprovider', "--junitxml=$logDir\junit.xml",
                    '-o', "log_file=$logDir\pytest.log") + $Tests
    Write-Host "> python $($pytestArgs -join ' ')"
    Push-Location $repoDir
    try {
        $ErrorActionPreference = 'Continue'
        & $python @pytestArgs 2>&1 | ForEach-Object { "$_" }
        $pytestRc = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    } finally { Pop-Location }
    Write-Host "pytest exit code: $pytestRc"
    if (Test-Path $resultsDir) { Copy-Item $resultsDir (Join-Path $logDir 'results') -Recurse -Force }
    if ($pytestRc -ne 0) { $failures.Add("tests failed (pytest exit $pytestRc); see $logDir\junit.xml") }
}
catch [System.OperationCanceledException] {
}
catch {
    $failures.Add($_.Exception.Message)
}
finally {
    # -----------------------------------------------------------------------
    # 5. Cleanup - always
    # -----------------------------------------------------------------------
    if ($KeepInstalled -and $installedOk -and -not $Cleanup) {
        Write-Step '5. Kept installed (-KeepInstalled)'
        [ordered]@{ msi = $Msi; version = $version; upgradeCode = $upgradeCode; withMA = [bool]$WithMA
                    keptAt = (Get-Date).ToString('s') } | ConvertTo-Json | Set-Content $keptFile -Encoding UTF8
        Write-Host "XClient left installed and HXSim running ($keptFile). The next run of this msi reuses them;" -ForegroundColor Yellow
        Write-Host 'a run without -KeepInstalled, or -Cleanup, cleans them up.' -ForegroundColor Yellow
    } else {
        Write-Step '5. Cleanup'
        $cleanupProblems = New-Object System.Collections.Generic.List[string]

        try {
            Invoke-RepoPython "from tests.util import hxsim_ioc; hxsim_ioc.stop_all_hxsim(); print('HXSim stopped')"
        } catch { $cleanupProblems.Add("stopping HXSim: $($_.Exception.Message)") }

        # Uninstall while the fake key still exists: ProductPreChecks also runs on uninstall.
        foreach ($code in Get-InstalledXClient $upgradeCode) {
            $rc = Invoke-Msiexec "/x $code" (Join-Path $logDir 'uninstall.log')
            Write-Host "msiexec /x $code exit code: $rc"
            if ($rc -ne 0 -and $rc -ne 3010) { $cleanupProblems.Add("uninstall of $code failed ($rc); see $logDir\uninstall.log") }
            if ($rc -eq 3010) { Write-Warning 'Uninstall asks for a reboot; reboot before the next run (the vscore drivers are removed at boot).' }
        }

        $stubDir = Join-Path $env:ProgramData 'Trellix\XClient'
        foreach ($f in 'ma_stub_policy.xml', 'ma_stub.log') {
            $p = Join-Path $stubDir $f
            if (Test-Path $p) { Remove-Item $p -Force -ErrorAction SilentlyContinue; Write-Host "Removed $p" }
        }

        if ($WithMA -and (Test-Path $cmdagent)) {
            $frmInst = Join-Path (Split-Path $cmdagent) 'x86\FrmInst.exe'
            $p = Start-Process $frmInst -ArgumentList '/forceuninstall', '/silent' -Wait -PassThru
            Write-Host "FrmInst.exe /forceuninstall exit code: $($p.ExitCode)"
            $deadline = (Get-Date).AddSeconds(300)
            while ((Test-Path $cmdagent) -and (Get-Date) -lt $deadline) { Start-Sleep 5 }
            if (Test-Path $cmdagent) { $cleanupProblems.Add("MA still installed ($cmdagent)") }
        }

        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $keyTool -Disable
        if ($LASTEXITCODE -ne 0) { $cleanupProblems.Add("fake_ma_key.ps1 -Disable failed ($LASTEXITCODE)") }

        if (Test-Path 'HKLM:\SOFTWARE\WOW6432Node\McAfee\Agent') { $cleanupProblems.Add('MA registry key still present') }
        $left = Get-InstalledXClient $upgradeCode
        if ($left.Count) { $cleanupProblems.Add("XClient still installed: $($left -join ', ')") }
        if (Test-Path (Join-Path $env:ProgramFiles 'Trellix\XClient\xclient.exe')) { $cleanupProblems.Add('xclient.exe still present') }

        if ($cleanupProblems.Count) {
            foreach ($c in $cleanupProblems) { Write-Host "CLEANUP PROBLEM: $c" -ForegroundColor Red }
            $failures.Add('cleanup incomplete')
        } else {
            Write-Host 'Host restored: no MA key, no XClient.' -ForegroundColor Green
            if (Test-Path $keptFile) { Remove-Item $keptFile -Force }
        }
    }
}

Write-Host ''
if ($failures.Count) {
    foreach ($f in $failures) { Write-Host "FAILED: $f" -ForegroundColor Red }
    Write-Host "RESULT: FAIL  (logs: $logDir)" -ForegroundColor Red
    Stop-Transcript | Out-Null
    exit 1
}
Write-Host "RESULT: PASS  (logs: $logDir)" -ForegroundColor Green
Stop-Transcript | Out-Null
exit 0
