[CmdletBinding()]
param(
    [string] $InputPort = 'UMC404HD 192k MIDI In',
    [string] $OutputStem = '',
    [ValidateRange(15, 300)] [int] $Seconds = 90,
    [ValidateRange(2, 30)] [int] $IdleSeconds = 5,
    [switch] $ConfirmReceiveOnly
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmReceiveOnly) {
    throw 'This opens a receive-only MIDI listener. Pass -ConfirmReceiveOnly, then initiate Send/Dump from the DDTi panel.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python environment is missing: $python"
}
if ([string]::IsNullOrWhiteSpace($OutputStem)) {
    $OutputStem = Join-Path $repoRoot 'local\ddti\greg-hybrid-base'
}
$stem = [IO.Path]::GetFullPath($OutputStem)
$parent = Split-Path -Parent $stem
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
}
foreach ($suffix in @('.syx', '.hex', '.json')) {
    if (Test-Path -LiteralPath ($stem + $suffix)) {
        throw "Refusing to replace an existing DDTi capture artifact: $($stem + $suffix)"
    }
}

Write-Output "Receive-only DDTi listener: $InputPort"
Write-Output 'Initiate the complete configuration dump from the DDTi panel now. No MIDI output will be opened.'
& $python -m ddti.cli dump $stem --input $InputPort --listen --seconds $Seconds --idle-seconds $IdleSeconds
if ($LASTEXITCODE -ne 0) {
    throw "DDTi receive-only capture failed with exit code $LASTEXITCODE."
}

$dump = $stem + '.syx'
if (-not (Test-Path -LiteralPath $dump -PathType Leaf)) {
    throw "DDTi capture completed without the expected dump: $dump"
}
& $python -m ddti.cli transfer-plan $dump
if ($LASTEXITCODE -ne 0) {
    throw 'The received stream is not a complete validated DDTi configuration dump.'
}
Write-Output "Validated receive-only base dump: $dump"
Write-Output 'Next: select this file as DDTi base dump in Control Center, compile, then stage and review the generated semantic diff.'
