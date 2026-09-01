[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$temporary = Join-Path ([IO.Path]::GetTempPath()) ("drum-toolchain-live-script-test-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $runtime = Join-Path $temporary 'runtime-profile.yaml'
    $hash = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
    @(
        'format: rig-runtime-profile/v1'
        'status: planned'
        'target_status:'
        '  sd3: planned'
        '  drumgizmo: planned'
        'deployment: simulation'
        "source_sha256: $hash"
    ) | Set-Content -LiteralPath $runtime -Encoding utf8NoBOM
    $config = Join-Path $temporary 'live-session.json'
    [ordered]@{
        schema_version = 1
        renderer = 'sd3'
        renderer_output = 'fixture-renderer-output'
        converter = @{ path = (Join-Path $PSHOME 'powershell.exe'); arguments = @() }
        sd3 = @{ path = (Join-Path $PSHOME 'powershell.exe'); arguments = @() }
        runtime_profile = @{ path = $runtime; project_hash = $hash }
        required_ports = @()
        required_inputs = @()
        required_outputs = @()
        asio_buffer_confirmation = 'manual test fixture'
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $config -Encoding utf8NoBOM
    $report = (& (Join-Path $PSScriptRoot 'live-preflight.ps1') -Config $config | ConvertFrom-Json)
    if ($report.status -ne 'blocked') { throw 'Simulation runtime profile unexpectedly passed live preflight.' }
    $problems = @($report.problems)
    if ($problems -notcontains "runtime_profile target 'sd3' must be ready; current status is 'planned'") {
        throw 'Live preflight did not reject a non-ready SD3 runtime target.'
    }
    if ($problems -notcontains 'runtime_profile.deployment must be live; simulation artifacts cannot launch a live session') {
        throw 'Live preflight did not reject a simulation runtime profile.'
    }
    if ($problems -notcontains "runtime_profile.validation_stage must be hardware-verified before live play; current stage is 'missing'") {
        throw 'Live preflight did not fail closed when validation_stage was absent.'
    }
    @(
        'format: rig-runtime-profile/v1'
        'status: planned'
        'target_status:'
        '  sd3: ready'
        '  drumgizmo: planned'
        'deployment: simulation'
        "source_sha256: $hash"
    ) | Set-Content -LiteralPath $runtime -Encoding utf8NoBOM
    $targetReadyReport = (& (Join-Path $PSScriptRoot 'live-preflight.ps1') -Config $config | ConvertFrom-Json)
    if (@($targetReadyReport.problems) -contains "runtime_profile target 'sd3' must be ready; current status is 'planned'") {
        throw 'Live preflight ignored the renderer-specific ready status.'
    }
    if (@($targetReadyReport.problems) -notcontains 'runtime_profile.deployment must be live; simulation artifacts cannot launch a live session') {
        throw 'Renderer-specific readiness accidentally bypassed the live deployment gate.'
    }
    @(
        'format: rig-runtime-profile/v1'
        'status: ready'
        'target_status:'
        '  sd3: ready'
        '  drumgizmo: ready'
        'deployment: live'
        'validation_stage: post-flash-validation-pending'
        "source_sha256: $hash"
    ) | Set-Content -LiteralPath $runtime -Encoding utf8NoBOM
    $flashOnlyReport = (& (Join-Path $PSScriptRoot 'live-preflight.ps1') -Config $config | ConvertFrom-Json)
    if (@($flashOnlyReport.problems) -notcontains "runtime_profile.validation_stage must be hardware-verified before live play; current stage is 'post-flash-validation-pending'") {
        throw 'Live preflight did not reject a configured-only profile pending pad validation.'
    }
    $campaign = Join-Path $temporary 'measurement-campaign'
    New-Item -ItemType Directory -Path $campaign | Out-Null
    $sourceProject = Join-Path $repoRoot 'profiles\projects\metalcore-r15-chain-simulator.yaml'
    [ordered]@{
        kind = 'drum-live-measurement-campaign/v1'
        source_project = $sourceProject
        source_sha256 = (Get-FileHash -LiteralPath $sourceProject -Algorithm SHA256).Hash.ToLowerInvariant()
        trace_requests = @([ordered]@{
            id = 'ddrum4.kick.hit.note-n000'
            source = 'ddrum4'
            physical = 'kick.hit'
            matcher = @{ source = 'ddrum4'; type = 'note'; note = 0 }
            trace = 'traces/ddrum4__kick-hit__note-n000.jsonl'
        })
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $campaign 'live-measurement-plan.json') -Encoding utf8NoBOM
    $preview = (& (Join-Path $PSScriptRoot 'capture-greg-hybrid-live-trace.ps1') -Campaign $campaign) -join "`n"
    if ($preview -notmatch 'Preview only: no MIDI port was opened') {
        throw 'Guided measurement preview did not prove that MIDI remained closed.'
    }
    if (Test-Path -LiteralPath (Join-Path $campaign 'traces')) {
        throw 'Guided measurement preview unexpectedly wrote a trace directory.'
    }

    $blockedState = Join-Path $temporary 'blocked-live-state.json'
    $blocked = $false
    try {
        & (Join-Path $PSScriptRoot 'start-live.ps1') -Config $config -StateFile $blockedState -ConfirmStart -Confirm:$false | Out-Null
    } catch {
        $blocked = $_.Exception.Message -match 'preflight'
    }
    if (-not $blocked) {
        throw 'start-live did not fail closed when the preflight rejected the simulation runtime.'
    }
    if (Test-Path -LiteralPath $blockedState) {
        throw 'A blocked live launch unexpectedly wrote session state.'
    }

    $completedReport = Join-Path $temporary 'completed-live-report.json'
    [ordered]@{
        kind = 'greg-hybrid-live-session-report'; schema_version = 1; run_id = 'fixture'
        status = 'running'; started_utc = [DateTime]::UtcNow.ToString('o'); ended_utc = $null
        process_results = @(); power_plan = @{ status = 'pending'; restored = $false }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $completedReport -Encoding utf8NoBOM
    $completedState = Join-Path $temporary 'completed-live-state.json'
    [ordered]@{
        kind = 'live-session-state'; schema_version = 1; processes = @()
        previous_power_scheme = $null; report_path = $completedReport
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $completedState -Encoding utf8NoBOM
    & (Join-Path $PSScriptRoot 'stop-live.ps1') -StateFile $completedState -Confirm:$false | Out-Null
    if (Test-Path -LiteralPath $completedState) {
        throw 'stop-live retained completed transient state.'
    }
    $completed = Get-Content -LiteralPath $completedReport -Raw | ConvertFrom-Json
    if ($completed.status -ne 'stopped' -or [string]::IsNullOrWhiteSpace([string]$completed.ended_utc)) {
        throw 'stop-live did not finalize the persistent health report.'
    }

    $requirements = Get-Content -LiteralPath (Join-Path $repoRoot 'deployment\windows-live\requirements.lock.txt')
    if (@($requirements | Where-Object { $_ -and $_ -notmatch '^[A-Za-z0-9_.-]+==[^\s=]+ --hash=sha256:[0-9a-f]{64}$' }).Count) {
        throw 'Portable bundle requirements must pin every direct and transitive dependency to an exact wheel hash.'
    }
    $builderText = Get-Content -LiteralPath (Join-Path $repoRoot 'scripts\build-greg-hybrid-live-bundle.ps1') -Raw
    if (([regex]::Matches($builderText, '--require-hashes')).Count -lt 2) {
        throw 'Portable bundle construction must require hashes for both wheel download and installation.'
    }
    $payloadGuard = Join-Path $repoRoot 'scripts\assert-tools-only-payload.ps1'
    $shareableFixture = Join-Path $temporary 'shareable-fixture'
    New-Item -ItemType Directory -Path $shareableFixture | Out-Null
    'safe' | Set-Content -LiteralPath (Join-Path $shareableFixture 'README.md') -Encoding ascii
    & $payloadGuard -Root $shareableFixture | Out-Null
    'private' | Set-Content -LiteralPath (Join-Path $shareableFixture 'leaked.sd3p') -Encoding ascii
    $privateBlocked = $false
    try {
        & $payloadGuard -Root $shareableFixture | Out-Null
    } catch {
        $privateBlocked = $_.Exception.Message -match 'forbidden'
    }
    if (-not $privateBlocked) {
        throw 'The tools-only payload policy did not reject a private SD3 preset.'
    }
    $bundleFixture = Join-Path $temporary 'bundle-fixture'
    New-Item -ItemType Directory -Path $bundleFixture | Out-Null
    $fixtureInstaller = Join-Path $bundleFixture 'Install-Live-Rig.ps1'
    Copy-Item -LiteralPath (Join-Path $repoRoot 'deployment\windows-live\Install-Live-Rig.ps1') -Destination $fixtureInstaller
    $payload = Join-Path $bundleFixture 'payload.txt'
    'fixture' | Set-Content -LiteralPath $payload -Encoding ascii
    $fixtureFiles = @($payload, $fixtureInstaller) | ForEach-Object {
        [ordered]@{
            path = [IO.Path]::GetFileName($_)
            size = (Get-Item -LiteralPath $_).Length
            sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    [ordered]@{
        kind = 'greg-hybrid-live-bundle/v1'
        bundle_id = 'fixture'
        files = @($fixtureFiles)
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $bundleFixture 'bundle-manifest.json') -Encoding utf8NoBOM
    $deepDestination = Join-Path $temporary ('deep-' + ('x' * 190))
    $deepBlocked = $false
    try {
        & (Join-Path $bundleFixture 'Install-Live-Rig.ps1') -DestinationRoot $deepDestination -NoDesktopShortcuts | Out-Null
    } catch {
        $deepBlocked = $_.Exception.Message -match 'too deep'
    }
    if (-not $deepBlocked) { throw 'Portable installer did not reject a projected Win32 path beyond its native-DLL safety limit.' }
    if (Test-Path -LiteralPath $deepDestination) { throw 'Rejected portable installation unexpectedly wrote its destination.' }

    $rollbackFixture = Join-Path $temporary 'rollback-bundle-fixture'
    New-Item -ItemType Directory -Path $rollbackFixture | Out-Null
    $rollbackInstaller = Join-Path $rollbackFixture 'Install-Live-Rig.ps1'
    Copy-Item -LiteralPath (Join-Path $repoRoot 'deployment\windows-live\Install-Live-Rig.ps1') -Destination $rollbackInstaller
    $rollbackPayload = Join-Path $rollbackFixture 'payload.txt'
    'fixture' | Set-Content -LiteralPath $rollbackPayload -Encoding ascii
    $failingDiagnostic = Join-Path $rollbackFixture 'Test-Live-Rig.ps1'
    "exit 1" | Set-Content -LiteralPath $failingDiagnostic -Encoding ascii
    $rollbackFiles = @($rollbackPayload, $failingDiagnostic, $rollbackInstaller) | ForEach-Object {
        [ordered]@{
            path = [IO.Path]::GetFileName($_)
            size = (Get-Item -LiteralPath $_).Length
            sha256 = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    [ordered]@{
        kind = 'greg-hybrid-live-bundle/v1'; bundle_id = 'broken-update'; files = @($rollbackFiles)
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $rollbackFixture 'bundle-manifest.json') -Encoding utf8NoBOM
    $rollbackRoot = Join-Path $temporary 'rollback-install'
    New-Item -ItemType Directory -Path $rollbackRoot | Out-Null
    $oldCurrent = [ordered]@{ kind = 'greg-hybrid-live-current-install/v1'; bundle_id = 'previous'; path = 'previous-path' }
    $oldCurrent | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $rollbackRoot 'current.json') -Encoding utf8NoBOM
    $updateBlocked = $false
    try {
        & (Join-Path $rollbackFixture 'Install-Live-Rig.ps1') -DestinationRoot $rollbackRoot -NoDesktopShortcuts | Out-Null
    } catch {
        $updateBlocked = $_.Exception.Message -match 'previous active version was preserved'
    }
    if (-not $updateBlocked) { throw 'Portable installer did not fail a broken copied-version diagnostic.' }
    $preserved = Get-Content -LiteralPath (Join-Path $rollbackRoot 'current.json') -Raw | ConvertFrom-Json
    if ($preserved.bundle_id -ne 'previous' -or $preserved.path -ne 'previous-path') {
        throw 'Failed portable update changed the active installation pointer.'
    }
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
Write-Output 'live launcher safety tests passed'
