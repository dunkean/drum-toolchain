[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$vsDev = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $vsDev)) {
    throw "Visual Studio developer environment not found: $vsDev"
}

$outputDirectory = Join-Path $repoRoot 'build\firmware-core'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
Push-Location $repoRoot
try {
    cmd /d /c scripts\test-firmware-core.cmd
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { throw "firmware bridge core tests failed with exit code $LASTEXITCODE" }
