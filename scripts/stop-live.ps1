[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)] [string] $StateFile,
    [switch] $PowerPlanRestored
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'live-common.ps1')
if (-not (Test-Path -LiteralPath $StateFile)) { throw "No live session state: $StateFile" }
$state = Read-LiveJson -Path $StateFile
if ($state.kind -ne 'live-session-state') { throw 'Refusing an unrecognised state document.' }
if (-not [string]::IsNullOrWhiteSpace([string]$state.previous_power_scheme) -and -not $PowerPlanRestored) {
    throw 'The session owns a power-plan change. Run restore-live instead of stop-live.'
}
$processResults = [System.Collections.Generic.List[object]]::new()
foreach ($entry in @($state.processes)) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if ($process) {
        $recordedPath = [IO.Path]::GetFullPath([string]$entry.path)
        $actualPath = try { [IO.Path]::GetFullPath([string]$process.Path) } catch { $null }
        if ($null -eq $actualPath -or -not [string]::Equals($recordedPath, $actualPath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "PID $($entry.pid) no longer matches recorded executable '$recordedPath'; refusing to stop it."
        }
        if (-not $PSCmdlet.ShouldProcess("$($entry.name) PID $($entry.pid)", 'Stop owned live process')) { continue }
        Stop-Process -Id $entry.pid -ErrorAction Stop
        $processResults.Add([ordered]@{ name = $entry.name; pid = $entry.pid; result = 'stopped_by_session' })
        Write-Output "Stopped $($entry.name) PID $($entry.pid)"
    } else {
        $processResults.Add([ordered]@{ name = $entry.name; pid = $entry.pid; result = 'already_exited' })
    }
}
if (-not $WhatIfPreference) {
    $reportPathProperty = $state.PSObject.Properties['report_path']
    $reportPath = if ($null -ne $reportPathProperty) { [string]$reportPathProperty.Value } else { '' }
    if (-not [string]::IsNullOrWhiteSpace($reportPath) -and (Test-Path -LiteralPath $reportPath)) {
        $report = Read-LiveJson -Path $reportPath
        if ($report.kind -ne 'greg-hybrid-live-session-report') {
            throw "Refusing an unrecognised live report: $reportPath"
        }
        $report.status = 'stopped'
        $report.ended_utc = [DateTime]::UtcNow.ToString('o')
        $report.process_results = @($processResults)
        if ($PowerPlanRestored) {
            $report.power_plan.status = 'restored'
            $report.power_plan.restored = $true
        }
        Write-LiveJson -Path $reportPath -Document $report
        Write-Output "Finalized persistent health report: $reportPath"
    }
}
if ($PSCmdlet.ShouldProcess($StateFile, 'Remove completed live session state')) {
    Remove-Item -LiteralPath $StateFile
}
