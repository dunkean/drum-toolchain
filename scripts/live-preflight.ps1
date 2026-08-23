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
    $runtimeHash = [regex]::Match($runtimeText, '(?m)^source_sha256:\s*["'']?([0-9a-fA-F]{64})["'']?\s*$')
    if (-not $runtimeHash.Success) {
        $problems.Add('runtime_profile.path does not contain a rig-runtime-profile source_sha256')
    } elseif (-not [string]::Equals($runtimeHash.Groups[1].Value, [string]$session.runtime_profile.project_hash, [StringComparison]::OrdinalIgnoreCase)) {
        $problems.Add('runtime_profile.project_hash does not match source_sha256 in the compiled runtime profile')
    }
}
if ([string]::IsNullOrWhiteSpace([string]$session.asio_buffer_confirmation)) {
    $problems.Add('asio_buffer_confirmation must state the buffer verified manually in the driver')
}

$report = [ordered]@{
    kind = 'live-preflight-report'; schema_version = 1; timestamp_utc = [DateTime]::UtcNow.ToString('o')
    config = $configPath.Path; required_ports = @($session.required_ports)
    runtime_profile = $session.runtime_profile
    status = if ($problems.Count) { 'blocked' } else { 'ready' }; problems = @($problems)
    note = 'Ports and ASIO buffer are declared/user-confirmed: this script intentionally does not open MIDI or change driver settings.'
}
$report | ConvertTo-Json -Depth 6
if ($RequireAll -and $problems.Count) { exit 2 }
