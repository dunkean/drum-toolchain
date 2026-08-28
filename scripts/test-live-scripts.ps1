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
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
Write-Output 'live launcher safety tests passed'
