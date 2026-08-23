[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)] [string] $Config,
    [Parameter(Mandatory = $true)] [string] $StateFile,
    [switch] $ConfirmApply
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmApply -and -not $WhatIfPreference) {
    throw 'Changing the live power plan is explicit; pass -ConfirmApply after reviewing the session configuration.'
}
$configPath = Resolve-Path -LiteralPath $Config
$statePath = Resolve-Path -LiteralPath $StateFile
$configDocument = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.kind -ne 'live-session-state') { throw 'Refusing an unrecognised state document.' }
if (-not [string]::IsNullOrWhiteSpace([string]$state.previous_power_scheme)) {
    throw 'This session already owns a power-plan change; restore it before applying another one.'
}
$targetScheme = [string]$configDocument.low_latency_power_scheme_guid
if ($targetScheme -notmatch '^[0-9a-fA-F-]{36}$') {
    throw 'low_latency_power_scheme_guid must be an explicit GUID from powercfg /list.'
}
$activeText = (& powercfg.exe /getactivescheme | Out-String)
if ($LASTEXITCODE -ne 0 -or $activeText -notmatch '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})') {
    throw 'Could not read the current Windows power plan GUID.'
}
$previousScheme = $Matches[1]

if (-not $PSCmdlet.ShouldProcess($targetScheme, "Record $previousScheme, activate live plan, and set owned PIDs to High")) {
    Write-Output 'No low-latency setting was changed.'
    exit 0
}
$state.previous_power_scheme = $previousScheme
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding utf8NoBOM
& powercfg.exe /setactive $targetScheme
if ($LASTEXITCODE -ne 0) {
    throw "Could not activate power plan $targetScheme. The previous GUID remains recorded; run restore-live."
}
foreach ($entry in @($state.processes)) {
    $process = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if ($null -eq $process) { continue }
    $recordedPath = [IO.Path]::GetFullPath([string]$entry.path)
    $actualPath = try { [IO.Path]::GetFullPath([string]$process.Path) } catch { $null }
    if ($null -eq $actualPath -or -not [string]::Equals($recordedPath, $actualPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PID $($entry.pid) no longer matches recorded executable '$recordedPath'; refusing to change its priority."
    }
    try { $process.PriorityClass = 'High' } catch { Write-Warning "Could not set High priority for $($entry.name): $($_.Exception.Message)" }
}
Write-Output "Low-latency settings applied; exact previous power plan recorded as $previousScheme."
