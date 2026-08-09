[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$vsDev = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat'
$cmake = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
if (-not (Test-Path -LiteralPath $vsDev) -or -not (Test-Path -LiteralPath $cmake)) {
    throw 'Visual Studio CMake toolchain is unavailable.'
}

Push-Location $repoRoot
try {
    cmd /d /c scripts\test-modernizer-core.cmd
    if ($LASTEXITCODE -ne 0) { throw "modernizer core tests failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
