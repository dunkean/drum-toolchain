[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Output ("Repository root: {0}" -f $repoRoot)
& (Join-Path $PSScriptRoot 'verify-environment.ps1')
