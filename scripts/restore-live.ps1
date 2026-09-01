[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([Parameter(Mandatory = $true)] [string] $StateFile)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'live-common.ps1')
if (-not (Test-Path -LiteralPath $StateFile)) { Write-Output 'No interrupted live session state found.'; exit 0 }
$state = Read-LiveJson -Path $StateFile
if ($state.kind -ne 'live-session-state') { throw 'Refusing an unrecognised state document.' }
$previousScheme = [string]$state.previous_power_scheme
if (-not [string]::IsNullOrWhiteSpace($previousScheme)) {
    if ($PSCmdlet.ShouldProcess($previousScheme, 'Restore the exact power plan recorded by this live session')) {
        & powercfg.exe /setactive $previousScheme
        if ($LASTEXITCODE -ne 0) { throw "Could not restore power plan $previousScheme" }
        Write-Output "Restored power plan $previousScheme"
    }
}
& (Join-Path $PSScriptRoot 'stop-live.ps1') -StateFile $StateFile -PowerPlanRestored -WhatIf:$WhatIfPreference -Confirm:$false
Write-Output 'Recorded live processes stopped and owned settings restored.'
