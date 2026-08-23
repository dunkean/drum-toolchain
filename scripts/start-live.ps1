[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)] [string] $Config,
    [Parameter(Mandatory = $true)] [string] $StateFile,
    [switch] $ConfirmStart
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmStart -and -not $WhatIfPreference) { throw 'Starting live applications is explicit; pass -ConfirmStart after running live-preflight.' }
& (Join-Path $PSScriptRoot 'live-preflight.ps1') -Config $Config -RequireAll | Write-Output
$configPath = Resolve-Path -LiteralPath $Config
$session = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
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
            [Environment]::SetEnvironmentVariable('DDRUM4_RUNTIME_PROFILE', $runtimeProfilePath, 'Process')
            [Environment]::SetEnvironmentVariable('DDRUM4_RENDERER_TARGET', $rendererTarget, 'Process')
            $restoreConverterEnvironment = $true
        }
        try {
            $process = Start-Process -FilePath $executablePath -ArgumentList $arguments -PassThru
        } finally {
            if ($restoreConverterEnvironment) {
                [Environment]::SetEnvironmentVariable('DDRUM4_RUNTIME_PROFILE', $previousRuntimeProfile, 'Process')
                [Environment]::SetEnvironmentVariable('DDRUM4_RENDERER_TARGET', $previousRendererTarget, 'Process')
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
$state = [ordered]@{
    kind = 'live-session-state'; schema_version = 1; started_utc = [DateTime]::UtcNow.ToString('o')
    config = $configPath.Path; processes = @($started); previous_power_scheme = $null
    note = 'Only PIDs recorded here may be stopped by stop-live. No global power plan was changed.'
}
$parent = Split-Path -Parent $StateFile
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $StateFile -Encoding utf8NoBOM
Write-Output "Live session started; state: $StateFile"
