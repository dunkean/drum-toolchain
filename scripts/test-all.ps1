[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Output 'No migrated application tests are registered yet.'
Write-Output 'This script becomes the single test entry point as M2-M7 land.'

if (-not (Test-Path (Join-Path $repoRoot 'docs/repository-migration.md'))) {
    throw 'Repository migration log is missing.'
}
