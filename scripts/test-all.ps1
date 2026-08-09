[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

$pythonPaths = @(
    (Join-Path $repoRoot 'packages\drum-domain\src'),
    (Join-Path $repoRoot 'apps\drum-sampler\src'),
    (Join-Path $repoRoot 'apps\ddrum4-bank-builder\src'),
    (Join-Path $repoRoot 'tools\midi-lab\src')
)
$env:PYTHONPATH = $pythonPaths -join [IO.Path]::PathSeparator

if (-not (Test-Path (Join-Path $repoRoot 'docs/repository-migration.md'))) {
    throw 'Repository migration log is missing.'
}

Write-Output 'Running shared Python domain, sampler, bank-builder, and MIDI-lab tests.'
Push-Location $repoRoot
try {
    python -m unittest discover -s tests\python -v
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
