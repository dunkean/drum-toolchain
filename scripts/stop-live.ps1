[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)] [string] $StateFile,
    [switch] $PowerPlanRestored
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $StateFile)) { throw "No live session state: $StateFile" }
$state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
if ($state.kind -ne 'live-session-state') { throw 'Refusing an unrecognised state document.' }
if (-not [string]::IsNullOrWhiteSpace([string]$state.previous_power_scheme) -and -not $PowerPlanRestored) {
    throw 'The session owns a power-plan change. Run restore-live instead of stop-live.'
}
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
        Write-Output "Stopped $($entry.name) PID $($entry.pid)"
    }
}
if ($PSCmdlet.ShouldProcess($StateFile, 'Remove completed live session state')) {
    Remove-Item -LiteralPath $StateFile
}
