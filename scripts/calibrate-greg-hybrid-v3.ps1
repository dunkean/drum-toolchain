[CmdletBinding()]
param(
    [ValidateSet('Targeted', 'Full')] [string] $Mode = 'Targeted',
    [switch] $ConfirmCapture,
    [switch] $ConfirmPresetLoaded
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmCapture) {
    throw 'Calibration sends MIDI and records audio. Pass -ConfirmCapture after checking the SD3/UMC route.'
}
if (-not $ConfirmPresetLoaded) {
    throw 'Load Greg Hybrid r15 MegaKit v3 in SD3, then pass -ConfirmPresetLoaded.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$session = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v4\capture-session.json'
$preset = Join-Path $repoRoot 'captures\sd3\Greg_Hybrid_r15_MegaKit_v3.sd3p'
$output = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v4\calibration-wav'
$reportName = if ($Mode -eq 'Full') { 'calibration.json' } else { 'calibration-targeted-v3.json' }
$report = Join-Path $repoRoot ("build\capture\greg-hybrid-r15-full-v4\reports\$reportName")
$expectedHash = '7a339e9f3eb417b9793b353bcb177a9648ba19126b07aa1b4624e794c6d7eef3'

foreach ($required in ($python, $session, $preset)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required calibration input is missing: $required"
    }
}

$arguments = @(
    '-m', 'drum_sampler.cli', 'calibrate',
    '--session', $session,
    '--preset-file', $preset,
    '--expected-preset-sha256', $expectedHash,
    '--output-directory', $output,
    '--report', $report,
    '--preferred-velocity', '110',
    '--duration-seconds', '1.5',
    '--confirm-capture',
    '--confirm-preset-loaded'
)

if ($Mode -eq 'Targeted') {
    foreach ($selector in @(
        'tom2.electronic',
        'rim1.rimshot',
        'snare1.deftones',
        'rim2.rimshot',
        'snare2.sleep',
        'tom1.sleep',
        'tom2.sleep',
        'tom3.sleep',
        'tom4.sleep'
    )) {
        $arguments += @('--only', $selector)
    }
}

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "$Mode calibration failed with exit code $LASTEXITCODE. Review $report before changing the preset."
}

Write-Output "$Mode calibration passed: $report"
if ($Mode -eq 'Targeted') {
    Write-Output 'This targeted report cannot unlock the full capture campaign. Run again with -Mode Full after reviewing it.'
}
