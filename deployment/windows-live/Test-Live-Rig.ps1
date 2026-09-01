[CmdletBinding()]
param([switch] $RequirePlayable)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $root 'bundle-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$problems = [System.Collections.Generic.List[string]]::new()
$python = Join-Path $root '.venv\Scripts\python.exe'
$converter = Join-Path $root 'build\modernizer-desktop-msvc\ddrum4_converter_artefacts\Release\ddrum4 Converter.exe'
$reportPath = Join-Path $root 'build\rig\current\project-report.json'
$runtimePath = Join-Path $root 'build\rig\current\runtime-profile.yaml'

foreach ($required in @($python, $converter, $reportPath, $runtimePath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { $problems.Add("missing required bundle file: $required") }
}

$pythonFacts = $null
if (Test-Path -LiteralPath $python) {
    $previousBytecodeSetting = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
        $facts = & $python -c "import json,sys; import yaml,mido,rtmidi,numpy,scipy,sounddevice,soundcard,jsonschema,PySide6; import control_center,ddti,ddrum4_bank,drum_sampler,drum_domain,midi_lab,rig_compiler; print(json.dumps({'python':sys.version.split()[0],'pyside':PySide6.__version__}))"
        if ($LASTEXITCODE -ne 0) { throw 'embedded Python import probe returned a non-zero exit code' }
        $pythonFacts = $facts | ConvertFrom-Json
        & $python -m control_center.cli --help *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Control Center CLI smoke failed' }
    } catch {
        $problems.Add("embedded tool runtime failed: $($_.Exception.Message)")
    } finally {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousBytecodeSetting, 'Process')
    }
}

$project = $null
if (Test-Path -LiteralPath $reportPath) {
    try { $project = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { $problems.Add("compiled project report is invalid: $($_.Exception.Message)") }
}
$stage = if ($null -ne $project) { [string]$project.validation_stage } else { 'missing' }
$deploymentReadiness = if ($stage -eq 'hardware-verified') { 'candidate-playable' } else { 'awaiting-hardware-validation' }

if ($RequirePlayable) {
    if ($null -eq $project -or [string]$project.deployment -ne 'live' -or $stage -ne 'hardware-verified') {
        $problems.Add("bundle project is not hardware-verified (deployment=$($project.deployment), stage=$stage)")
    }
    $config = Join-Path $root 'local\greg-hybrid-live-session.local.json'
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
        $problems.Add('local live session is not configured; run Configure-Live-Rig.cmd')
    } else {
        try { & (Join-Path $root 'scripts\live-preflight.ps1') -Config $config -RequireAll | Out-Null }
        catch { $problems.Add("live preflight failed: $($_.Exception.Message)") }
    }
}

$result = [ordered]@{
    kind = 'greg-hybrid-live-deployment-diagnostic/v1'
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    bundle_id = [string]$manifest.bundle_id
    bundle_scope = [string]$manifest.scope
    embedded_runtime = $pythonFacts
    project = if ($null -ne $project) { @{ deployment = $project.deployment; validation_stage = $stage; source_sha256 = $project.source_sha256 } } else { $null }
    deployment_readiness = $deploymentReadiness
    status = if ($problems.Count) { 'blocked' } else { 'ready' }
    problems = @($problems)
    note = 'This diagnostic imports tools and inspects files only. MIDI is not opened and no process is launched.'
}
$result | ConvertTo-Json -Depth 6
if ($problems.Count) { exit 1 }
