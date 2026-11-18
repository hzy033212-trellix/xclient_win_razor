# Orbit XClient installer builds on Artifactory; dot-sourced by Get-FakeMaMsi.ps1.
# Layout (the one tests\util\artifactory.py reads):
#   XClientInstaller-local/WIN_<a.b.c>/b<build>.<n>/xclient_<a.b.c>.<build>_x64.msi   (<n> is a rebuild counter)
#   next to it the installer build's Jenkins console log, *-ConsoleText-<n>.log
# Needs ARTIFACTORY_USER / ARTIFACTORY_TOKEN.

$script:ArtifactoryUrl = 'https://artifactory.trellix.com/artifactory/'

function Get-ArtifactoryHeaders {
    if (-not $env:ARTIFACTORY_USER -or -not $env:ARTIFACTORY_TOKEN) {
        throw 'Set ARTIFACTORY_USER and ARTIFACTORY_TOKEN (Artifactory user name and identity token).'
    }
    $pair = [Text.Encoding]::UTF8.GetBytes("$($env:ARTIFACTORY_USER):$($env:ARTIFACTORY_TOKEN)")
    @{ Authorization = 'Basic ' + [Convert]::ToBase64String($pair) }
}

# Names of the files and folders in an Artifactory folder.
function Get-ArtifactoryChildren([string]$Folder, $Headers) {
    $info = Invoke-RestMethod -Uri ($ArtifactoryUrl + 'api/storage/' + $Folder) -Headers $Headers -UseBasicParsing
    @($info.children | ForEach-Object { $_.uri.TrimStart('/') })
}

# The newest *passed* Orbit build of a release: the highest b<build>.<n> folder (of the newest
# $Scan) that has its msi and whose console log ends with "Finished: SUCCESS" - the lookup
# win_razor's CI uses for 'latest'. Returns @{ Version; Path } (Path: the msi's Artifactory path).
function Find-LatestPassedOrbit([string]$Release, $Headers, [int]$Scan = 15) {
    $base = "XClientInstaller-local/WIN_$Release"
    $folders = foreach ($name in (Get-ArtifactoryChildren $base $Headers)) {
        if ($name -match '^b(\d+)\.(\d+)$') { [pscustomobject]@{ Name = $name; Build = [int]$Matches[1]; N = [int]$Matches[2] } }
    }
    foreach ($f in ($folders | Sort-Object Build, N -Descending | Select-Object -First $Scan)) {
        $msi = "xclient_$Release.$($f.Build)_x64.msi"
        $names = @(Get-ArtifactoryChildren "$base/$($f.Name)" $Headers)
        $log = $names | Where-Object { $_ -match '-ConsoleText-\d+\.log$' } | Select-Object -First 1
        if (-not ($names -contains $msi) -or -not $log) { Write-Host "  $base/$($f.Name): no msi or console log, skipped"; continue }
        $text = (Invoke-WebRequest -Uri ($ArtifactoryUrl + "$base/$($f.Name)/$log") -Headers $Headers -UseBasicParsing).Content
        if ($text -is [byte[]]) { $text = [Text.Encoding]::UTF8.GetString($text) }
        if ($text.TrimEnd() -match 'Finished: SUCCESS$') {
            return [pscustomobject]@{ Version = "$Release.$($f.Build)"; Path = "$base/$($f.Name)/$msi" }
        }
        Write-Host "  $base/$($f.Name): build did not pass, skipped"
    }
    throw "No passed build with an msi among the newest $Scan in $ArtifactoryUrl$base"
}

# The Orbit msi of one version: the highest b<build>.<n> folder of that build that contains its msi.
function Find-OrbitMsi([string]$Release, [int]$Build, $Headers) {
    $base = "XClientInstaller-local/WIN_$Release"
    $folders = foreach ($name in (Get-ArtifactoryChildren $base $Headers)) {
        if ($name -match '^b(\d+)\.(\d+)$' -and [int]$Matches[1] -eq $Build) {
            [pscustomobject]@{ Name = $name; N = [int]$Matches[2] }
        }
    }
    foreach ($f in ($folders | Sort-Object N -Descending)) {
        $msi = "xclient_$Release.${Build}_x64.msi"
        if ((Get-ArtifactoryChildren "$base/$($f.Name)" $Headers) -contains $msi) {
            return [pscustomobject]@{ Version = "$Release.$Build"; Path = "$base/$($f.Name)/$msi" }
        }
    }
    throw "No xclient_$Release.${Build}_x64.msi in $ArtifactoryUrl$base"
}

# Downloads an artifact to $Dest (kept if it already matches Artifactory's SHA-256).
function Get-Artifact([string]$Path, [string]$Dest, $Headers) {
    $sha = (Invoke-RestMethod -Uri ($ArtifactoryUrl + 'api/storage/' + $Path) -Headers $Headers -UseBasicParsing).checksums.sha256
    if ((Test-Path $Dest) -and (Get-FileHash $Dest).Hash -eq $sha) { Write-Host "  cached: $Dest"; return }
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    Write-Host "  downloading $ArtifactoryUrl$Path"
    $ProgressPreference = 'SilentlyContinue'   # the progress bar slows Invoke-WebRequest down a lot
    Invoke-WebRequest -Uri ($ArtifactoryUrl + $Path) -Headers $Headers -OutFile "$Dest.part" -UseBasicParsing
    if ((Get-FileHash "$Dest.part").Hash -ne $sha) { Remove-Item "$Dest.part"; throw "SHA-256 mismatch downloading $Path" }
    Move-Item "$Dest.part" $Dest -Force
}
