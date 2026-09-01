[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [string] $LiveProject,
    [Parameter(Mandatory = $true)] [string] $RendererOutput,
    [Parameter(Mandatory = $true)] [string] $AsioBufferConfirmation,
    [Parameter(Mandatory = $true)] [ValidatePattern('^[0-9a-fA-F-]{36}$')] [string] $PowerSchemeGuid,
    [string] $Converter = '',
    [string] $Sd3 = 'C:\Program Files\Toontrack\Superior Drummer\Superior Drummer 3.exe',
    [string] $Config = '',
    [switch] $ReplaceBuild
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'live-common.ps1')
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$projectPath = (Resolve-Path -LiteralPath $LiveProject).Path
$buildDirectory = Join-Path $repoRoot ('build\rig\' + [IO.Path]::GetFileNameWithoutExtension($projectPath))
if ([string]::IsNullOrWhiteSpace($Config)) { $Config = Join-Path $repoRoot 'local\greg-hybrid-live-session.local.json' }
$configPath = [IO.Path]::GetFullPath($Config)
if ([string]::IsNullOrWhiteSpace($Converter)) {
    $Converter = Join-Path $repoRoot 'build\modernizer-desktop-msvc\ddrum4_converter_artefacts\Release\ddrum4 Converter.exe'
}

& (Join-Path $PSScriptRoot 'build-rig.ps1') -Project $projectPath -Output $buildDirectory -Replace:$ReplaceBuild -Confirm:$false | Write-Output
$reportPath = Join-Path $buildDirectory 'project-report.json'
$runtimePath = Join-Path $buildDirectory 'runtime-profile.yaml'
$report = Read-LiveJson -Path $reportPath
$firmware = $report.artifacts | Where-Object name -eq 'firmware-project-mapping'
$runtimeStatusJson = & $python -c "import json,sys,yaml; d=yaml.safe_load(open(sys.argv[1],encoding='utf-8')); print(json.dumps((d.get('target_status') or {}).get('sd3',d.get('status','planned'))))" $runtimePath
if ($LASTEXITCODE -ne 0) { throw 'Could not read the SD3 target status from the compiled runtime.' }
$runtimeStatus = $runtimeStatusJson | ConvertFrom-Json
if ($report.deployment -ne 'live' -or $report.validation_stage -ne 'hardware-verified' -or
    $runtimeStatus -ne 'ready' -or $firmware.status -ne 'ready') {
    throw "The selected project is not deployable: deployment=$($report.deployment), runtime.sd3=$runtimeStatus, firmware=$($firmware.status). Complete the measured live promotion first."
}
foreach ($path in @($Converter, $Sd3, $runtimePath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required live file not found: $path" }
}
$portJson = & $python -c "import json,sys,yaml; d=yaml.safe_load(open(sys.argv[1],encoding='utf-8')); print(json.dumps({'inputs':[v['endpoint'] for v in d['sources'].values()],'control':(d.get('control_bus') or {}).get('endpoint')}))" $projectPath
if ($LASTEXITCODE -ne 0) { throw 'Could not read exact live endpoints from the validated project.' }
$ports = $portJson | ConvertFrom-Json
$sourceEndpoints = @($ports.inputs)
$controlOutput = [string]$ports.control
$requiredOutputs = @($RendererOutput)
if ($controlOutput) { $requiredOutputs += $controlOutput }
$session = [ordered]@{
    schema_version = 1
    renderer = 'sd3'
    renderer_output = $RendererOutput
    converter = @{ path = (Resolve-Path -LiteralPath $Converter).Path; arguments = @() }
    sd3 = @{ path = (Resolve-Path -LiteralPath $Sd3).Path; arguments = @() }
    runtime_profile = @{ path = (Resolve-Path -LiteralPath $runtimePath).Path; project_hash = [string]$report.source_sha256 }
    required_inputs = @($sourceEndpoints)
    required_outputs = @($requiredOutputs | Select-Object -Unique)
    required_ports = @(@($sourceEndpoints) + @($requiredOutputs) | Select-Object -Unique)
    asio_buffer_confirmation = $AsioBufferConfirmation
    low_latency_power_scheme_guid = $PowerSchemeGuid
    health_report_directory = Join-Path (Split-Path -Parent $configPath) 'reports'
    note = 'Generated from a measured deployment:live project. Device-specific and intentionally gitignored.'
}
if ((Test-Path -LiteralPath $configPath) -and -not $ReplaceBuild) {
    throw "Local live configuration already exists: $configPath. Pass -ReplaceBuild to regenerate it explicitly."
}
if ($PSCmdlet.ShouldProcess($configPath, 'Write device-specific live session configuration')) {
    Write-LiveJson -Path $configPath -Document $session
}
Write-Output "Prepared local live session: $configPath"
Write-Output 'Run live-preflight first; the one-click launcher remains fail-closed if any exact port is missing.'
