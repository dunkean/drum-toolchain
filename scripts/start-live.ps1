[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)] [string] $Config,
    [Parameter(Mandatory = $true)] [string] $StateFile,
    [switch] $ConfirmStart
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmStart -and -not $WhatIfPreference) { throw 'Starting live applications is explicit; pass -ConfirmStart after running live-preflight.' }
. (Join-Path $PSScriptRoot 'live-common.ps1')
$global:LASTEXITCODE = 0
$preflightLines = @(& (Join-Path $PSScriptRoot 'live-preflight.ps1') -Config $Config -RequireAll)
$preflightExitCode = $LASTEXITCODE
$preflightLines | Write-Output
if ($preflightExitCode -ne 0) {
    throw "Live preflight failed closed with exit code $preflightExitCode; no process was started."
}
try {
    $preflight = (($preflightLines -join [Environment]::NewLine) | ConvertFrom-Json)
} catch {
    throw "Live preflight did not return a valid health report; no process was started: $($_.Exception.Message)"
}
if ([string]$preflight.status -ne 'ready') {
    throw "Live preflight status is '$($preflight.status)', not ready; no process was started."
}
$configPath = Resolve-Path -LiteralPath $Config
$session = Read-LiveJson -Path $configPath.Path
$runtimeProfilePath = (Resolve-Path -LiteralPath ([string]$session.runtime_profile.path)).Path
$rendererTarget = [string]$session.renderer
if (Test-Path -LiteralPath $StateFile) { throw "Interrupted/live session state exists: $StateFile. Review it, then run restore-live before starting again." }

$started = [System.Collections.Generic.List[object]]::new()
foreach ($name in @('converter', 'sd3')) {
    $entry = $session.$name
    $arguments = @($entry.arguments)
    $executablePath = (Resolve-Path -LiteralPath ([string]$entry.path)).Path
    if (-not $PSCmdlet.ShouldProcess($executablePath, "Start visible live application '$name'")) { continue }
    try {
        # Start-Process inherits the current process environment. Limit the
        # runtime settings to the owned Converter child, then restore this
        # script's environment before launching SD3 or returning to the user.
        $restoreConverterEnvironment = $false
        if ($name -eq 'converter') {
            $previousRuntimeProfile = [Environment]::GetEnvironmentVariable('DDRUM4_RUNTIME_PROFILE', 'Process')
            $previousRendererTarget = [Environment]::GetEnvironmentVariable('DDRUM4_RENDERER_TARGET', 'Process')
            $previousRendererOutput = [Environment]::GetEnvironmentVariable('DDRUM4_RENDERER_OUTPUT', 'Process')
            [Environment]::SetEnvironmentVariable('DDRUM4_RUNTIME_PROFILE', $runtimeProfilePath, 'Process')
            [Environment]::SetEnvironmentVariable('DDRUM4_RENDERER_TARGET', $rendererTarget, 'Process')
            [Environment]::SetEnvironmentVariable('DDRUM4_RENDERER_OUTPUT', [string]$session.renderer_output, 'Process')
            $restoreConverterEnvironment = $true
        }
        try {
            $process = Start-Process -FilePath $executablePath -ArgumentList $arguments -PassThru
        } finally {
            if ($restoreConverterEnvironment) {
                [Environment]::SetEnvironmentVariable('DDRUM4_RUNTIME_PROFILE', $previousRuntimeProfile, 'Process')
                [Environment]::SetEnvironmentVariable('DDRUM4_RENDERER_TARGET', $previousRendererTarget, 'Process')
                [Environment]::SetEnvironmentVariable('DDRUM4_RENDERER_OUTPUT', $previousRendererOutput, 'Process')
            }
        }
        try { $process.PriorityClass = 'High' } catch { Write-Warning "Could not set High priority for ${name}: $($_.Exception.Message)" }
        $started.Add([ordered]@{ name = $name; pid = $process.Id; path = $executablePath })
    } catch {
        foreach ($owned in $started) {
            $ownedProcess = Get-Process -Id $owned.pid -ErrorAction SilentlyContinue
            if ($ownedProcess) { Stop-Process -Id $owned.pid -ErrorAction SilentlyContinue }
        }
        throw
    }
}
if ($WhatIfPreference) {
    Write-Output 'WhatIf: no process was started and no session state was written.'
    exit 0
}
if ($started.Count -ne 2) {
    foreach ($owned in $started) {
        $ownedProcess = Get-Process -Id $owned.pid -ErrorAction SilentlyContinue
        if ($ownedProcess) { Stop-Process -Id $owned.pid -ErrorAction SilentlyContinue }
    }
    throw "Live launch was incomplete ($($started.Count)/2 owned processes); started processes were rolled back."
}
$runId = ([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$reportDirectoryProperty = $session.PSObject.Properties['health_report_directory']
$reportDirectory = if ($null -ne $reportDirectoryProperty) { [string]$reportDirectoryProperty.Value } else { '' }
if ([string]::IsNullOrWhiteSpace($reportDirectory)) {
    $reportDirectory = Join-Path (Split-Path -Parent ([IO.Path]::GetFullPath($StateFile))) 'reports'
} elseif (-not [IO.Path]::IsPathRooted($reportDirectory)) {
    $reportDirectory = Join-Path (Split-Path -Parent $configPath.Path) $reportDirectory
}
$reportPath = Join-Path ([IO.Path]::GetFullPath($reportDirectory)) ("greg-hybrid-live-$runId.json")
$state = [ordered]@{
    kind = 'live-session-state'; schema_version = 1; started_utc = [DateTime]::UtcNow.ToString('o')
    config = $configPath.Path; processes = @($started); previous_power_scheme = $null
    report_path = $reportPath
    note = 'Only PIDs recorded here may be stopped by stop-live. The persistent report survives session shutdown.'
}
$report = [ordered]@{
    kind = 'greg-hybrid-live-session-report'; schema_version = 1; run_id = $runId
    status = 'running'; started_utc = $state.started_utc; ended_utc = $null
    config = @{ path = $configPath.Path; sha256 = Get-LiveFileSha256 -Path $configPath.Path }
    runtime_profile = @{
        path = $runtimeProfilePath
        sha256 = Get-LiveFileSha256 -Path $runtimeProfilePath
        project_hash = [string]$session.runtime_profile.project_hash
    }
    renderer = [string]$session.renderer
    renderer_output = [string]$session.renderer_output
    asio_buffer_confirmation = [string]$session.asio_buffer_confirmation
    preflight = $preflight
    processes = @($started)
    process_results = @()
    power_plan = @{
        status = 'pending'
        requested = [string]$session.low_latency_power_scheme_guid
        previous = $null
        restored = $false
    }
    hardware_io = 'ports-opened-by-owned-converter-only'
}
try {
    Write-LiveJson -Path $reportPath -Document $report
    Write-LiveJson -Path $StateFile -Document $state
} catch {
    foreach ($owned in $started) {
        $ownedProcess = Get-Process -Id $owned.pid -ErrorAction SilentlyContinue
        if ($ownedProcess) { Stop-Process -Id $owned.pid -ErrorAction SilentlyContinue }
    }
    if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath -Force }
    throw
}
Write-Output "Live session started; state: $StateFile"
Write-Output "Persistent health report: $reportPath"
