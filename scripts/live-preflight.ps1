[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [string] $Config,
    [switch] $RequireAll
)

$ErrorActionPreference = 'Stop'
$configPath = Resolve-Path -LiteralPath $Config
$session = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$problems = [System.Collections.Generic.List[string]]::new()

if ([string]$session.renderer -ne 'sd3') {
    $problems.Add('renderer must be sd3 for the Windows live session; use the Linux DrumGizmo session profile for drumgizmo.')
}

foreach ($name in @('converter', 'sd3')) {
    $configured = $session.$name
    if ($null -eq $configured -or [string]::IsNullOrWhiteSpace([string]$configured.path)) {
        $problems.Add("$name.path is missing")
    } elseif (-not (Test-Path -LiteralPath $configured.path)) {
        $problems.Add("$name.path not found: $($configured.path)")
    }
}
foreach ($port in @($session.required_ports)) {
    if ([string]::IsNullOrWhiteSpace([string]$port)) { $problems.Add('required_ports contains an empty name') }
}
if ([string]::IsNullOrWhiteSpace([string]$session.renderer_output)) {
    $problems.Add('renderer_output must name the exact unique MIDI output opened automatically by the Converter.')
}
$requiredInputs = @($session.required_inputs)
$requiredOutputs = @($session.required_outputs)
foreach ($port in @($requiredInputs + $requiredOutputs)) {
    if ([string]::IsNullOrWhiteSpace([string]$port)) { $problems.Add('required_inputs/required_outputs contains an empty name') }
}
$duplicatePorts = @($session.required_ports | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
if ($duplicatePorts.Count) {
    $problems.Add("required_ports must contain unique endpoint names; duplicates: $($duplicatePorts -join ', ')")
}
if ($null -eq $session.runtime_profile -or [string]::IsNullOrWhiteSpace([string]$session.runtime_profile.path)) {
    $problems.Add('runtime_profile.path is missing')
} elseif (-not (Test-Path -LiteralPath $session.runtime_profile.path)) {
    $problems.Add("runtime_profile.path not found: $($session.runtime_profile.path)")
}
if ([string]::IsNullOrWhiteSpace([string]$session.runtime_profile.project_hash)) {
    $problems.Add('runtime_profile.project_hash must contain the hash printed by the compiled runtime profile')
} elseif ([string]$session.runtime_profile.project_hash -notmatch '^[0-9a-fA-F]{64}$') {
    $problems.Add('runtime_profile.project_hash must be a SHA-256 value')
} elseif (Test-Path -LiteralPath $session.runtime_profile.path) {
    $runtimeText = Get-Content -LiteralPath $session.runtime_profile.path -Raw
    $runtimeFormat = [regex]::Match($runtimeText, '(?m)^format:\s*["'']?([^\r\n"'']+)["'']?\s*$')
    $runtimeDeployment = [regex]::Match($runtimeText, '(?m)^deployment:\s*["'']?([^\r\n"'']+)["'']?\s*$')
    $runtimeHash = [regex]::Match($runtimeText, '(?m)^source_sha256:\s*["'']?([0-9a-fA-F]{64})["'']?\s*$')
    if (-not $runtimeFormat.Success -or $runtimeFormat.Groups[1].Value.Trim() -ne 'rig-runtime-profile/v1') {
        $problems.Add('runtime_profile.path is not a rig-runtime-profile/v1 artifact')
    }
    if (-not $runtimeDeployment.Success -or $runtimeDeployment.Groups[1].Value.Trim() -ne 'live') {
        $problems.Add('runtime_profile.deployment must be live; simulation artifacts cannot launch a live session')
    }
    if (-not $runtimeHash.Success) {
        $problems.Add('runtime_profile.path does not contain a rig-runtime-profile source_sha256')
    } elseif (-not [string]::Equals($runtimeHash.Groups[1].Value, [string]$session.runtime_profile.project_hash, [StringComparison]::OrdinalIgnoreCase)) {
        $problems.Add('runtime_profile.project_hash does not match source_sha256 in the compiled runtime profile')
    }
}
if ([string]::IsNullOrWhiteSpace([string]$session.asio_buffer_confirmation)) {
    $problems.Add('asio_buffer_confirmation must state the buffer verified manually in the driver')
}

# Listing names is deliberately read-only.  The preflight never opens an input
# and never sends MIDI; it only catches a renamed/missing USB or loopMIDI port
# before a live launch is attempted.
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$runtimeTargetStatus = $null
if ($null -ne $session.runtime_profile -and (Test-Path -LiteralPath $session.runtime_profile.path)) {
    try {
        $runtimeFactsJson = & $python -c "import json,sys,yaml; d=yaml.safe_load(open(sys.argv[1],encoding='utf-8')); r=sys.argv[2]; print(json.dumps({'status':(d.get('target_status') or {}).get(r,d.get('status','planned'))}))" ([string]$session.runtime_profile.path) ([string]$session.renderer)
        if ($LASTEXITCODE -ne 0) { throw 'runtime YAML parser returned a non-zero exit code.' }
        $runtimeTargetStatus = ($runtimeFactsJson | ConvertFrom-Json).status
        if ([string]$runtimeTargetStatus -ne 'ready') {
            $problems.Add("runtime_profile target '$($session.renderer)' must be ready; current status is '$runtimeTargetStatus'")
        }
    } catch {
        $problems.Add("Could not read renderer-specific runtime status: $($_.Exception.Message)")
    }
}
$midiInventory = $null
try {
    $inventoryJson = & $python -c "import json, mido; print(json.dumps({'inputs': list(mido.get_input_names()), 'outputs': list(mido.get_output_names())}))"
    if ($LASTEXITCODE -ne 0) { throw 'Python MIDI backend returned a non-zero exit code.' }
    $midiInventory = $inventoryJson | ConvertFrom-Json
    $allPorts = @($midiInventory.inputs) + @($midiInventory.outputs)
    foreach ($port in @($session.required_ports)) {
        if ($allPorts -notcontains $port) { $problems.Add("required MIDI port is not visible: $port") }
    }
    foreach ($port in $requiredInputs) {
        if (@($midiInventory.inputs) -notcontains $port) { $problems.Add("required MIDI input is not visible: $port") }
    }
    foreach ($port in $requiredOutputs) {
        if (@($midiInventory.outputs) -notcontains $port) { $problems.Add("required MIDI output is not visible: $port") }
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$session.renderer_output) -and
            @($midiInventory.outputs) -notcontains [string]$session.renderer_output) {
        $problems.Add("renderer MIDI output is not visible: $($session.renderer_output)")
    }
} catch {
    $problems.Add("Could not list MIDI ports read-only: $($_.Exception.Message)")
}

$report = [ordered]@{
    kind = 'live-preflight-report'; schema_version = 1; timestamp_utc = [DateTime]::UtcNow.ToString('o')
    config = $configPath.Path; required_ports = @($session.required_ports)
    required_inputs = $requiredInputs; required_outputs = $requiredOutputs; midi_inventory = $midiInventory
    runtime_profile = $session.runtime_profile
    status = if ($problems.Count) { 'blocked' } else { 'ready' }; problems = @($problems)
    note = 'MIDI ports were listed read-only; this script intentionally does not open MIDI, send MIDI, or change driver settings.'
}
$report | ConvertTo-Json -Depth 6
if ($RequireAll -and $problems.Count) { exit 2 }
