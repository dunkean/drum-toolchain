[CmdletBinding()]
param(
    [ValidatePattern('^COM[0-9]+$')]
    [string]$Port = 'COM3',
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repoRoot 'firmware\ddrum4-midi-bridge'
$python = 'C:\Python313\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

Write-Host "Building DDrum4 MIDI bridge (Uno)."
Push-Location $project
try {
    & $python -m platformio run -e uno
    if ($LASTEXITCODE -ne 0) { throw "Uno build failed with exit code $LASTEXITCODE" }
    if (-not $BuildOnly) {
        Write-Host "Flashing $Port. The MIDI shield must be in PGM mode."
        & $python -m platformio run -e uno --target upload --upload-port $Port
        if ($LASTEXITCODE -ne 0) { throw "Uno upload failed with exit code $LASTEXITCODE" }
        Write-Host 'Flash verified. Move the shield switch to RUN before MIDI use.'
    }
} finally {
    Pop-Location
}
