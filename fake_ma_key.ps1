<#
.SYNOPSIS
    Adds or removes the fake Trellix Agent registry key that lets the XClient msi install without MA.

.DESCRIPTION
    The msi's ProductPreChecks custom action aborts unless
    HKLM\SOFTWARE\WOW6432Node\McAfee\Agent exists with AgentVersion >= 5.8.2.
    The real MA owns that same key, so the fake one is tagged with a FakeForXClient value and only a
    tagged key is ever removed. A real MA key is never touched.

    Exit codes: 0 done (or nothing to do), 1 refused (real MA key present), 2 bad arguments.

.EXAMPLE
    .\fake_ma_key.ps1 -Enable
.EXAMPLE
    .\fake_ma_key.ps1 -Disable
#>
[CmdletBinding()]
param(
    [switch]$Enable,
    [switch]$Disable,
    [string]$AgentVersion = '5.8.2'
)

$ErrorActionPreference = 'Stop'
$parent = 'HKLM:\SOFTWARE\WOW6432Node\McAfee'
$key    = "$parent\Agent"
$marker = 'FakeForXClient'

if ($Enable -eq $Disable) {
    Write-Host 'Usage: fake_ma_key.ps1 -Enable | -Disable'
    exit 2
}

function Test-FakeKey { (Test-Path $key) -and ($null -ne (Get-ItemProperty $key -Name $marker -ErrorAction SilentlyContinue)) }

if ($Enable) {
    if (Test-FakeKey) { Write-Host "Fake MA key already present: $key"; exit 0 }
    if (Test-Path $key) { Write-Warning "$key exists without the $marker marker (real MA?); not touching it."; exit 1 }
    New-Item $key -Force | Out-Null
    New-ItemProperty $key -Name AgentVersion -Value $AgentVersion -PropertyType String -Force | Out-Null
    New-ItemProperty $key -Name $marker -Value 1 -PropertyType DWord -Force | Out-Null
    Write-Host "Fake MA key added: $key (AgentVersion=$AgentVersion, $marker=1)"
    exit 0
}

if (-not (Test-Path $key)) { Write-Host "No MA key: $key"; exit 0 }
if (-not (Test-FakeKey)) { Write-Warning "$key has no $marker marker (real MA?); not removing it."; exit 1 }
Remove-Item $key -Recurse -Force
# Drop the McAfee parent too if nothing else lives there.
$p = Get-Item $parent -ErrorAction SilentlyContinue
if ($p -and $p.SubKeyCount -eq 0 -and $p.ValueCount -eq 0) { Remove-Item $parent -Force }
Write-Host "Fake MA key removed: $key"
exit 0
