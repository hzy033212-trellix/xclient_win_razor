# Shared helpers: logging, native command execution, version parsing, VS env.

$script:LogDir = $null

function Write-Banner([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 78) -ForegroundColor Cyan
}

function Write-Info([string]$Text) { Write-Host "  $Text" }
function Write-Ok([string]$Text)   { Write-Host "  [ OK ] $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text){ Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "  [FAIL] $Text" -ForegroundColor Red }

function Stop-Build([string]$Text) {
    Write-Host ""
    Write-Host "BUILD STOPPED: $Text" -ForegroundColor Red
    if ($script:LogDir) { Write-Host "Logs: $script:LogDir" -ForegroundColor Red }
    exit 1
}

function Initialize-LogDir([string]$Root) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:LogDir = Join-Path $Root "logs\$stamp"
    New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
    return $script:LogDir
}

function ConvertTo-CmdArg([string]$Arg) {
    if ($Arg -eq "") { return '""' }
    if ($Arg -match '[\s"&|<>^()]') { return '"' + ($Arg -replace '"', '\"') + '"' }
    return $Arg
}

# Runs a command line through cmd.exe with stderr merged at the OS level.
# ProcessStartInfo is used (not the & operator) because Windows PowerShell 5.1
# mangles embedded quotes and wraps native stderr in terminating ErrorRecords.
# $OnLine is invoked for every output line. Returns the exit code.
function Invoke-CmdLine([string]$Line, [string]$WorkDir, [scriptblock]$OnLine) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = '/d /s /c "' + $Line + ' 2>&1"'
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    while ($null -ne ($l = $proc.StandardOutput.ReadLine())) { & $OnLine $l }
    $proc.WaitForExit()
    return $proc.ExitCode
}

function Join-CmdLine([string]$Exe, [string[]]$ArgList) {
    return ((@($Exe) + $ArgList) | ForEach-Object { ConvertTo-CmdArg $_ }) -join " "
}

# Runs a native command, streaming output to the console (unless -Quiet) and
# to $LogName under the log dir. Returns the exit code.
function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string]$Exe,
        [string[]]$ArgList = @(),
        [string]$WorkDir = (Get-Location).Path,
        [string]$LogName,
        [switch]$Quiet
    )
    $line = Join-CmdLine $Exe $ArgList
    if (-not $Quiet) { Write-Info "> $line" }
    $writer = $null
    if ($LogName -and $script:LogDir) {
        $writer = New-Object System.IO.StreamWriter((Join-Path $script:LogDir $LogName), $true)
        $writer.WriteLine("> $line")
        $writer.WriteLine("(cwd: $WorkDir)")
    }
    try {
        $code = Invoke-CmdLine $line $WorkDir {
            param($l)
            if ($writer) { $writer.WriteLine($l) }
            if (-not $Quiet) { Write-Host $l }
        }
        if ($writer) { $writer.WriteLine("(exit code: $code)") }
    } finally {
        if ($writer) { $writer.Dispose() }
    }
    return $code
}

# Runs a native command and returns its merged output as a trimmed string
# (no console echo). Exit code is left in $script:LastNativeExit.
function Get-NativeOutput([string]$Exe, [string[]]$ArgList = @()) {
    $buf = New-Object System.Text.StringBuilder
    try {
        $script:LastNativeExit = Invoke-CmdLine (Join-CmdLine $Exe $ArgList) (Get-Location).Path {
            param($l) [void]$buf.AppendLine($l)
        }
    } catch {
        $script:LastNativeExit = -1
        return $null
    }
    return $buf.ToString().Trim()
}

function Invoke-Step([string]$Exe, [string[]]$ArgList, [string]$LogName,
                     [string]$WorkDir = (Get-Location).Path, [string]$FailMessage) {
    $code = Invoke-Native -Exe $Exe -ArgList $ArgList -WorkDir $WorkDir -LogName $LogName
    if ($code -ne 0) {
        if (-not $FailMessage) { $FailMessage = "'$Exe' exited with code $code" }
        Stop-Build "$FailMessage (see $(Join-Path $script:LogDir $LogName))"
    }
}

# Extracts the first dotted version number (e.g. 3.25.3) from text.
function Get-VersionFromText([string]$Text) {
    if ($Text -and $Text -match '(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?') {
        $parts = @($Matches[1], $Matches[2], $Matches[3], $Matches[4]) | Where-Object { $_ -ne $null -and $_ -ne "" }
        return [version]($parts -join ".")
    }
    return $null
}

function Get-VsWherePath {
    $p = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $p) { return $p }
    return $null
}

# Returns the install path of VS 2022 (17.x) with the x64 C++ toolset, or $null.
function Get-Vs2022Path {
    $vswhere = Get-VsWherePath
    if (-not $vswhere) { return $null }
    $path = Get-NativeOutput $vswhere @("-latest", "-products", "*", "-version", "[17.0,18.0)",
        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath")
    if ($path) { return ($path -split "`r?`n")[0].Trim() }
    return $null
}

# The MSVC toolset XClient is built with (VS 2022 17.5). Keep in step with
# tools\toolchain.ps1 VsBuildTools.MsvcPrefix, which setup.ps1 installs.
$script:MsvcVersionPrefix = "14.35"
# The Windows SDK XClient is built against (WDK 10.0.22621 tools and headers match it). Keep in
# step with tools\toolchain.ps1 VsBuildTools.SdkVersion.
$script:WinSdkVersion = "10.0.22621.0"

# The newest VC\Tools\MSVC\14.35.* folder of the VS install, or $null.
function Get-PinnedMsvcDir([string]$VsPath) {
    Get-ChildItem (Join-Path $VsPath "VC\Tools\MSVC") -Directory -Filter "$script:MsvcVersionPrefix.*" -ErrorAction SilentlyContinue |
        Sort-Object { [version]$_.Name } | Select-Object -Last 1
}

# Imports the x64 MSVC developer environment (vcvars64.bat) into this process,
# equivalent to running from an "x64 Native Tools Command Prompt for VS 2022", with
# the pinned MSVC toolset selected (-vcvars_ver) even if a newer one is the default.
function Import-VsDevEnv([string]$VsPath) {
    $vcvars = Join-Path $VsPath "VC\Auxiliary\Build\vcvars64.bat"
    if (-not (Test-Path $vcvars)) { Stop-Build "vcvars64.bat not found at $vcvars" }
    $msvc = Get-PinnedMsvcDir $VsPath
    if (-not $msvc) { Stop-Build "MSVC $script:MsvcVersionPrefix not found in $VsPath\VC\Tools\MSVC (run setup.ps1)" }
    if (-not (Test-Path (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\Include\$script:WinSdkVersion\um\windows.h"))) {
        Stop-Build "Windows SDK $script:WinSdkVersion not installed (run setup.ps1)"
    }
    $dump = New-Object System.Collections.Generic.List[string]
    $code = Invoke-CmdLine ('"' + $vcvars + '" ' + $script:WinSdkVersion + ' -vcvars_ver=' + $msvc.Name + ' >nul && set') (Get-Location).Path { param($l) $dump.Add($l) }
    if ($code -ne 0) { Stop-Build "Failed to run $vcvars" }
    foreach ($kv in $dump) {
        $i = $kv.IndexOf("=")
        if ($i -gt 0) { [Environment]::SetEnvironmentVariable($kv.Substring(0, $i), $kv.Substring($i + 1), "Process") }
    }
    if ($env:VCToolsVersion -ne $msvc.Name) { Stop-Build "vcvars64.bat selected MSVC '$env:VCToolsVersion', not $($msvc.Name)" }
    if ($env:WindowsSDKVersion.TrimEnd('\') -ne $script:WinSdkVersion) { Stop-Build "vcvars64.bat selected Windows SDK '$env:WindowsSDKVersion', not $script:WinSdkVersion" }
    # Conan's CMake helper passes this to XClient's configure as -DCMAKE_SYSTEM_VERSION, which
    # makes the Visual Studio generator use this SDK rather than the newest installed one.
    $env:CONAN_CMAKE_SYSTEM_VERSION = $script:WinSdkVersion
    Write-Ok "Imported MSVC x64 developer environment ($vcvars, MSVC $($msvc.Name), Windows SDK $script:WinSdkVersion)"
}

# True if the ASCII string $Needle occurs anywhere in the binary file.
function Test-BinaryContains([string]$Path, [string]$Needle) {
    if (-not (Test-Path $Path)) { return $false }
    $text = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($Path))
    return $text.Contains($Needle)
}

# Compares two header trees ignoring CRLF/LF differences. Returns the list of
# relative paths that are missing or differ (empty list = identical).
function Compare-HeaderTree([string]$Left, [string]$Right) {
    $diffs = New-Object System.Collections.Generic.List[string]
    $files = Get-ChildItem -Path $Left -Recurse -File -Include *.h, *.hxx
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($Left.TrimEnd('\').Length + 1)
        $other = Join-Path $Right $rel
        if (-not (Test-Path $other)) { $diffs.Add("missing in real: $rel"); continue }
        $a = [System.IO.File]::ReadAllText($f.FullName) -replace "`r`n", "`n"
        $b = [System.IO.File]::ReadAllText($other) -replace "`r`n", "`n"
        if ($a -ne $b) { $diffs.Add("differs: $rel") }
    }
    return ,$diffs
}
