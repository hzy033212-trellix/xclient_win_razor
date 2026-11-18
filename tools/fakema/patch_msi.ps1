<#
.SYNOPSIS
    Makes a fake-MA MSI from an Orbit XClient MSI by swapping in a fake-MA mxAgent.dll.

.DESCRIPTION
    Copies -Msi to -Out, replaces the mxAgent.dll in its embedded cabinet with -MxAgent (WiX DTF
    InstallPackage.UpdateFiles, which also updates the File table's size and version), gives it a new
    PackageCode (a different package from Orbit's, same ProductCode and version) and signs it with a
    test certificate made on this host. Every other file stays Orbit's, byte for byte.

    WiX DTF comes from setup.ps1 (NWR_ROOT\tools\dtf, NuGet). The certificate is a self-signed code
    signing certificate in Cert:\CurrentUser\My (made on first use, subject TestCertSubject below);
    msiexec doesn't need a trusted signature, so it is not added to any trust store.

.EXAMPLE
    .\tools\fakema\patch_msi.ps1 -Msi <orbit msi> -MxAgent <fake-MA mxAgent.dll> -Out <fake-MA msi>
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Msi,
    [Parameter(Mandatory)][string]$MxAgent,
    [Parameter(Mandatory)][string]$Out
)

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path (Split-Path $MyInvocation.MyCommand.Path)) 'toolchain.ps1')
$TestCertSubject = 'CN=new_win_razor fake-MA test signing'

$Msi = (Resolve-Path $Msi).Path
$MxAgent = (Resolve-Path $MxAgent).Path
$Out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
if (-not [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($MxAgent)).Contains('ma_stub.log')) {
    throw "$MxAgent is not a fake-MA build (no ma_stub.log marker)"
}

$dtf = $Toolchain.Dtf.Dir
foreach ($a in 'WindowsInstaller', 'WindowsInstaller.Package', 'Compression', 'Compression.Cab') {
    $dll = Join-Path $dtf "WixToolset.Dtf.$a.dll"
    if (-not (Test-Path $dll)) { throw "$dll not found: run setup.ps1" }
    Add-Type -Path $dll
}

function Get-TestCertificate {
    $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
            Where-Object { $_.Subject -eq $TestCertSubject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
            Sort-Object NotAfter -Descending | Select-Object -First 1
    if ($cert) { return $cert }
    Write-Host "Making the test signing certificate ($TestCertSubject, Cert:\CurrentUser\My)"
    New-SelfSignedCertificate -Type CodeSigningCert -Subject $TestCertSubject -CertStoreLocation Cert:\CurrentUser\My `
        -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 -NotAfter (Get-Date).AddYears(5)
}

New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
Copy-Item $Msi $Out -Force
$work = "$Out.work"
if (Test-Path $work) { Remove-Item $work -Recurse -Force }

$pkg = New-Object WixToolset.Dtf.WindowsInstaller.Package.InstallPackage $Out, ([WixToolset.Dtf.WindowsInstaller.DatabaseOpenMode]::Transact)
try {
    $file = $pkg.Files['mxAgent.dll']
    if (-not $file) { throw "No File-table entry 'mxAgent.dll' in $Msi" }
    # UpdateFiles takes the new file from <WorkingDirectory>\<SourcePath> and rebuilds the cabinet holding it.
    $pkg.WorkingDirectory = $work
    $pkg.CompressionLevel = [WixToolset.Dtf.Compression.CompressionLevel]::Max
    $src = Join-Path $work $file.SourcePath
    New-Item -ItemType Directory -Force -Path (Split-Path $src) | Out-Null
    Copy-Item $MxAgent $src
    Write-Host "Replacing $($file.TargetPath) in $(Split-Path $Out -Leaf) (rebuilds the cabinet, ~1 min)"
    $pkg.UpdateFiles([string[]]@('mxAgent.dll'))
    $pkg.SummaryInfo.RevisionNumber = [guid]::NewGuid().ToString('B').ToUpper()   # PackageCode
    $pkg.Commit()
}
finally {
    $pkg.Close()
    if (Test-Path $work) { Remove-Item $work -Recurse -Force }
}

$cert = Get-TestCertificate
$sig = Set-AuthenticodeSignature -FilePath $Out -Certificate $cert -HashAlgorithm SHA256
# Self-signed, so not trusted (Status UnknownError); what matters is that it is signed, by this certificate.
$check = Get-AuthenticodeSignature $Out
if (-not $check.SignerCertificate -or $check.SignerCertificate.Thumbprint -ne $cert.Thumbprint) {
    throw "Signing $Out failed: $($sig.StatusMessage)"
}
$sha = (Get-FileHash $Out).Hash
"$sha  $(Split-Path $Out -Leaf)" | Set-Content "$Out.sha256"
Write-Host "Fake-MA MSI: $Out ($([math]::Round((Get-Item $Out).Length / 1MB, 1)) MB, signed by $($cert.Subject))"
