[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Snapshot,
    [string] $SourceContract = '',
    [switch] $ConfirmApplied
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmApplied) {
    throw 'Pass -ConfirmApplied only after the custom Drum Map is sent, auto-saved on eDRUMin, and exported as this .edp snapshot.'
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$snapshotPath = [IO.Path]::GetFullPath($Snapshot)
if (-not (Test-Path -LiteralPath $snapshotPath -PathType Leaf)) {
    throw "eDRUMin snapshot does not exist: $snapshotPath"
}
if ([string]::IsNullOrWhiteSpace($SourceContract)) {
    $SourceContract = Join-Path $repoRoot 'build\rig\metalcore-r15\source-note-contract.yaml'
}
$contractPath = [IO.Path]::GetFullPath($SourceContract)
if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
    throw "Compiled source contract does not exist: $contractPath"
}
$contractText = Get-Content -LiteralPath $contractPath -Raw
$contractMatch = [regex]::Match($contractText, '(?m)^source_contract_sha256:\s*([0-9a-f]{64})\s*$')
if (-not $contractMatch.Success) {
    throw 'Compiled source contract has no source_contract_sha256.'
}
$profile = Join-Path $repoRoot 'profiles\physical\greg-hybrid-edrumin.yaml'
$receipt = [ordered]@{
    kind = 'greg-hybrid-edrumin-configuration-receipt/v1'
    status = 'user-confirmed'
    confirmed_at = (Get-Date).ToUniversalTime().ToString('o')
    device = 'eDrumIn BLACK'
    source_contract_sha256 = $contractMatch.Groups[1].Value
    profile = $profile
    profile_sha256 = (Get-FileHash -LiteralPath $profile -Algorithm SHA256).Hash.ToLowerInvariant()
    snapshot = $snapshotPath
    snapshot_sha256 = (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256).Hash.ToLowerInvariant()
    assertion = 'Global CH3 and Greg Hybrid Raw Source Map notes 0..8 were sent and auto-saved on the device.'
}
$directory = Join-Path $repoRoot 'local\edrumin'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$path = Join-Path $directory ("greg-hybrid-edrumin-receipt-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
[IO.File]::WriteAllText($path, (($receipt | ConvertTo-Json -Depth 10) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
Write-Output "Verified operator receipt: $path"

