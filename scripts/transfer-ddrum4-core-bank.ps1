[CmdletBinding()]
param(
    [string]$MidiOutput = 'UMC404HD 192k MIDI Out 9',
    [string]$BankReport = 'D:\Studio\ddrum4-b3\empty-module-core-bank-report-20260810.json',
    [string]$ReceiptDirectory = ('D:\Studio\ddrum4-transfers\core-' + (Get-Date -Format 'yyyyMMdd-HHmmss')),
    [switch]$ConfirmedEmptySoundMemory
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmedEmptySoundMemory) {
    throw 'Refusing bank transfer: first confirm SHIFT+MEM.LEFT = 8.12 and pass -ConfirmedEmptySoundMemory.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPaths = @(
    (Join-Path $repoRoot 'apps\ddrum4-bank-builder\src')
)
$env:PYTHONPATH = $pythonPaths -join [IO.Path]::PathSeparator

if (-not (Test-Path -LiteralPath $BankReport -PathType Leaf)) {
    throw "Bank report not found: $BankReport"
}

$report = Get-Content -LiteralPath $BankReport -Raw | ConvertFrom-Json
if ($report.capacity_blocks -ne 8120 -or $report.used_blocks -ne 1240 -or $report.sounds.Count -ne 13) {
    throw 'Core-bank report no longer matches the hardware-verified 8120/1240/13 baseline.'
}

$seenIds = @{}
foreach ($sound in $report.sounds) {
    $path = [IO.Path]::GetFullPath([string]$sound.path)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Sound file not found: $path"
    }
    $actualHash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne ([string]$sound.sha256).ToLowerInvariant()) {
        throw "Sound hash changed since hardware verification: $path"
    }
    $soundId = [IO.Path]::GetFileNameWithoutExtension($path)
    if ($seenIds.ContainsKey($soundId)) {
        throw "Duplicate sound ID in bank report: $soundId"
    }
    $seenIds[$soundId] = $true
}

New-Item -ItemType Directory -Path $ReceiptDirectory -Force | Out-Null

$index = 0
foreach ($sound in $report.sounds) {
    $index++
    $path = [IO.Path]::GetFullPath([string]$sound.path)
    $soundId = [IO.Path]::GetFileNameWithoutExtension($path)
    $receipt = Join-Path $ReceiptDirectory ($soundId + '.json')
    Write-Output "[$index/13] Sending $soundId ($($sound.encoded_blocks) blocks)"
    python -m ddrum4_bank.cli transfer-sound $path `
        --output $MidiOutput `
        --receipt $receipt `
        --sysex-pause 0.4 `
        --confirm-hardware-write
    if ($LASTEXITCODE -ne 0) {
        throw "Transfer stopped after $soundId with exit code $LASTEXITCODE"
    }
}

Write-Output "Core bank sent: 13 sounds, 1240 blocks. Receipts: $ReceiptDirectory"
