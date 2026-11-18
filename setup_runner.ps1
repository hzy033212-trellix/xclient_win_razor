<#
.SYNOPSIS
    Make this Windows host a GitHub Actions self-hosted runner of this repo (.github\workflows\tests.yml).

.DESCRIPTION
    Run from an Administrator prompt in a clone of this repo:

      powershell -ExecutionPolicy Bypass -File setup_runner.ps1 -Token <registration token>
      powershell -ExecutionPolicy Bypass -File setup_runner.ps1 -Pat <PAT>     (fetches the token)

    The registration token comes from the repo's Settings > Actions > Runners > New self-hosted
    runner (valid for one hour). Instead, -Pat (or GITHUB_PAT) is a token that may administer the
    repo (classic: "repo" scope; fine-grained: "Administration: read and write"); the script then
    gets the registration token itself.

    Steps:
      1. setup.ps1 (unless -SkipSetup): the tools under NWR_ROOT (C:\nwr) that the workflow uses.
         Set ARTIFACTORY_USER / ARTIFACTORY_TOKEN first so the Conan remotes get logged in.
      2. Downloads the latest actions/runner release (SHA-256 checked) into -RunnerDir.
      3. Registers it with the repo (labels self-hosted, Windows, X64, new-win-razor) and installs it
         as a Windows service running as LocalSystem (the tests need Administrator rights), with
         this repo's PortableGit on its PATH (actions/checkout needs git).

    -Remove unregisters the runner and removes its service (needs -Token = a removal token from
    the same Settings page, or -Pat).

    Then add the repository secrets ARTIFACTORY_USER, ARTIFACTORY_TOKEN and XCLIENT_GITHUB_TOKEN
    (see the workflow file's header).
#>
param(
    [string]$Token,
    [string]$Pat = $env:GITHUB_PAT,
    [string]$Repo,
    [string]$Name = "$env:COMPUTERNAME-nwr",
    [string]$Labels = 'new-win-razor',
    [string]$RunnerDir,
    [switch]$Remove,
    [switch]$SkipSetup
)

$ErrorActionPreference = 'Stop'
$repoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $repoDir 'tools\toolchain.ps1')
if (-not $RunnerDir) { $RunnerDir = Join-Path $NwrRoot 'runner' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

function Write-Step([string]$Message) { Write-Host ''; Write-Host "=== $Message" -ForegroundColor Cyan }
function Fail([string]$Message) { Write-Host $Message -ForegroundColor Red; exit 1 }

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail 'Run setup_runner.ps1 as Administrator.' }

# owner/repo of this clone's origin, e.g. https://github.com/owner/repo.git or git@github.com:owner/repo.git
if (-not $Repo) {
    $git = Get-ToolPath 'Git'
    if (-not (Test-Path $git)) { $git = 'git' }
    $origin = & $git -C $repoDir remote get-url origin
    if ($origin -notmatch 'github\.com[/:]([^/]+/[^/]+?)(\.git)?$') { Fail "Can't tell the GitHub repo from origin '$origin'; pass -Repo owner/repo." }
    $Repo = $Matches[1]
}
$url = "https://github.com/$Repo"
Write-Host "Repo: $url   runner: $Name   folder: $RunnerDir"

function Get-RunnerToken([string]$Kind) {
    if ($Token) { return $Token }
    if (-not $Pat) { Fail "Pass -Token (Settings > Actions > Runners of $url) or -Pat / GITHUB_PAT." }
    $r = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Repo/actions/runners/$Kind-token" `
        -Headers @{ Authorization = "Bearer $Pat"; Accept = 'application/vnd.github+json' }
    $r.token
}

$configured = Test-Path (Join-Path $RunnerDir '.runner')

if ($Remove) {
    if (-not $configured) { Write-Host "No runner configured in $RunnerDir."; exit 0 }
    Write-Step 'Unregister the runner'
    & (Join-Path $RunnerDir 'config.cmd') remove --token (Get-RunnerToken 'remove')
    if ($LASTEXITCODE -ne 0) { Fail "config.cmd remove failed ($LASTEXITCODE)" }
    Write-Host "Runner removed. $RunnerDir can be deleted." -ForegroundColor Green
    exit 0
}

if ($configured) {
    $info = Get-Content (Join-Path $RunnerDir '.runner') -Raw | ConvertFrom-Json
    Write-Host "A runner is already configured in ${RunnerDir}: '$($info.agentName)' for $($info.gitHubUrl). Run with -Remove first to re-register." -ForegroundColor Yellow
    Get-Service "actions.runner.*" -ErrorAction SilentlyContinue | Format-Table Name, Status, StartType -AutoSize
    exit 0
}
if (-not $Token -and -not $Pat) { Fail "Pass -Token (Settings > Actions > Runners of $url) or -Pat / GITHUB_PAT." }

# ---------------------------------------------------------------------------
if (-not $SkipSetup) {
    Write-Step '1. setup.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoDir 'setup.ps1')
    if ($LASTEXITCODE -ne 0) { Fail "setup.ps1 failed ($LASTEXITCODE); fix it and run setup_runner.ps1 again (or -SkipSetup)." }
}
$gitCmd = Join-Path $Toolchain.Git.Dir 'cmd'
if (-not (Test-Path (Join-Path $gitCmd 'git.exe'))) { Fail "No PortableGit in $gitCmd; run setup.ps1 first." }

# ---------------------------------------------------------------------------
Write-Step '2. Download the runner'
$release = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/runner/releases/latest' -Headers @{ Accept = 'application/vnd.github+json' }
$asset = $release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-[\d.]+\.zip$' } | Select-Object -First 1
if (-not $asset) { Fail "No win-x64 zip in actions/runner $($release.tag_name)" }
# The expected hash: the asset's digest, else the release notes' <!-- BEGIN SHA win-x64 --> line.
$sha = if ($asset.digest -match '^sha256:([0-9a-f]{64})$') { $Matches[1] }
       elseif ($release.body -match 'BEGIN SHA win-x64 -->([0-9a-f]{64})<') { $Matches[1] }
if (-not $sha) { Fail "No SHA-256 for $($asset.name) in the release" }
$zip = Get-Download $asset.browser_download_url (Join-Path $NwrRoot "downloads\$($asset.name)")
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $sha) { Remove-Item $zip -Force; Fail "$($asset.name) SHA-256 mismatch: got $actual, expected $sha" }
New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null
Expand-Archive -Path $zip -DestinationPath $RunnerDir -Force
Write-Host "  $($asset.name) unpacked into $RunnerDir"

# ---------------------------------------------------------------------------
Write-Step '3. Register and install the service'
# The runner saves the PATH it is configured with (.path) for its jobs: put PortableGit first.
$env:PATH = "$gitCmd;$env:PATH"
# --work w: a short work folder (C:\nwr\runner\w\...), as the tests write deep paths.
& (Join-Path $RunnerDir 'config.cmd') --unattended --url $url --token (Get-RunnerToken 'registration') `
    --name $Name --labels $Labels --work w --replace `
    --runasservice --windowslogonaccount 'NT AUTHORITY\SYSTEM'
if ($LASTEXITCODE -ne 0) { Fail "config.cmd failed ($LASTEXITCODE)" }

$svc = Get-Service "actions.runner.*$Name*" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $svc) { Fail 'The runner service was not created.' }
if ($svc.Status -ne 'Running') { Start-Service $svc.Name }
Write-Host ''
Write-Host "Runner '$Name' registered with $url and running as service $($svc.Name) (LocalSystem)." -ForegroundColor Green
Write-Host "Next: add the repository secrets ARTIFACTORY_USER, ARTIFACTORY_TOKEN, XCLIENT_GITHUB_TOKEN ($url/settings/secrets/actions)."
exit 0
