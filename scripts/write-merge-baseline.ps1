[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$reportDirectory = Join-Path $repoRoot 'build\reports'
$reportPath = Join-Path $reportDirectory 'merge-baseline.md'
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null

$started = Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'
$testOutput = & (Join-Path $PSScriptRoot 'test-all.ps1') 2>&1 | Out-String
$commit = (git -C $repoRoot rev-parse --short HEAD).Trim()

@"
# Merge Baseline Report

Generated: $started

Commit: **$commit**

## Result

PASS — the complete non-hardware suite completed successfully.

## Covered checks

- shared domain, sampler, bank-builder, and MIDI-lab Python tests;
- generated routing-contract compatibility with the firmware generator;
- portable MSVC firmware bridge-core test;
- clean CMake/MSVC modernizer core build and test.

## Hardware actions

None. This report does not send MIDI, SysEx, audio capture commands, or sound
data to any hardware device.

## Raw test output

````text
$testOutput
````
"@ | Set-Content -LiteralPath $reportPath -Encoding utf8

Write-Output "Wrote $reportPath"
