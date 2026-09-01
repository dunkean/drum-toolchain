[CmdletBinding()]
param(
    [string] $Sd3 = 'C:\Program Files\Toontrack\Superior Drummer\Superior Drummer 3.exe',
    [string] $RendererOutput = '',
    [string] $AsioBufferConfirmation = '',
    [string] $PowerSchemeGuid = '',
    [switch] $NonInteractive
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$report = Get-Content -LiteralPath (Join-Path $root 'build\rig\current\project-report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$report.deployment -ne 'live' -or [string]$report.validation_stage -ne 'hardware-verified') {
    throw "This bundle is installed but cannot be configured for play yet: deployment=$($report.deployment), stage=$($report.validation_stage). Rebuild it from the promoted hardware-verified project after the pad campaign."
}

$python = Join-Path $root '.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($RendererOutput)) {
    if ($NonInteractive) { throw '-RendererOutput is required with -NonInteractive.' }
    Write-Output 'Visible MIDI outputs (read-only inventory):'
    & $python -c "import mido; [print(' - '+x) for x in mido.get_output_names()]"
    $RendererOutput = Read-Host 'Exact MIDI output feeding SD3'
}
if ([string]::IsNullOrWhiteSpace($AsioBufferConfirmation)) {
    if ($NonInteractive) { throw '-AsioBufferConfirmation is required with -NonInteractive.' }
    $AsioBufferConfirmation = Read-Host 'Confirmed UMC ASIO setting (example: 48 kHz / 64 samples)'
}
if ([string]::IsNullOrWhiteSpace($PowerSchemeGuid)) {
    $active = (& powercfg /getactivescheme | Out-String)
    $match = [regex]::Match($active, '[0-9a-fA-F-]{36}')
    if ($match.Success) { $PowerSchemeGuid = $match.Value }
}
if ([string]::IsNullOrWhiteSpace($PowerSchemeGuid) -or $PowerSchemeGuid -notmatch '^[0-9a-fA-F-]{36}$') {
    throw 'Could not resolve an explicit Windows power scheme GUID.'
}
if (-not (Test-Path -LiteralPath $Sd3 -PathType Leaf)) {
    if ($NonInteractive) { throw "SD3 executable not found: $Sd3" }
    $Sd3 = Read-Host 'Full path to Superior Drummer 3.exe'
}

& (Join-Path $root 'scripts\prepare-greg-hybrid-live.ps1') `
    -LiveProject (Join-Path $root 'deployment\live-project.yaml') `
    -RendererOutput $RendererOutput `
    -AsioBufferConfirmation $AsioBufferConfirmation `
    -PowerSchemeGuid $PowerSchemeGuid `
    -Converter (Join-Path $root 'build\modernizer-desktop-msvc\ddrum4_converter_artefacts\Release\ddrum4 Converter.exe') `
    -Sd3 $Sd3 `
    -Config (Join-Path $root 'local\greg-hybrid-live-session.local.json') `
    -ReplaceBuild

& (Join-Path $root 'scripts\live-preflight.ps1') -Config (Join-Path $root 'local\greg-hybrid-live-session.local.json')
Write-Output 'Configuration written. When every required port is visible, use Launch-Greg-Hybrid-Live.cmd.'
