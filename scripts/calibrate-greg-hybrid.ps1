[CmdletBinding()]
param(
    [ValidateSet('Targeted', 'Full')] [string] $Mode = 'Targeted',
    [switch] $ConfirmCapture,
    [switch] $ConfirmPresetLoaded,
    [switch] $ConfirmMegaKitMidiMap
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmCapture) {
    throw 'Calibration sends MIDI and records audio. Pass -ConfirmCapture after checking the SD3/UMC route.'
}
if (-not $ConfirmPresetLoaded) {
    throw 'Load Greg Hybrid r15 MegaKit v23 in SD3, then pass -ConfirmPresetLoaded.'
}
if (-not $ConfirmMegaKitMidiMap) {
    throw 'Select the neutral SD3 e-drum preset Kit_Metalcore_MidiMapping_Capture_V1, then pass -ConfirmMegaKitMidiMap.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$session = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v23\capture-session.json'
$preset = Join-Path $repoRoot 'captures\sd3\Greg_Hybrid_r15_MegaKit_v23_approved.sd3p'
$output = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v23\calibration-wav'
$reportName = if ($Mode -eq 'Full') { 'calibration.json' } else { 'calibration-targeted-v23.json' }
$report = Join-Path $repoRoot ("build\capture\greg-hybrid-r15-full-v23\reports\$reportName")
$expectedHash = 'ecc54520557bdbc970051e7a391b6b7da611955bfe62132f00b9ee87c1474a20'
$expectedWindowPattern = 'Greg[_ ]Hybrid[_ ]r15[_ ]MegaKit[_ ]v23'

foreach ($required in ($python, $session, $preset)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required calibration input is missing: $required"
    }
}

$sd3Processes = @(Get-Process -Name 'Superior Drummer 3' -ErrorAction SilentlyContinue)
if (-not $sd3Processes) {
    throw 'Superior Drummer 3 is not running. Start SD3 and load Greg Hybrid r15 MegaKit v23.'
}
$matchingPreset = @($sd3Processes | Where-Object { $_.MainWindowTitle -match $expectedWindowPattern })
if (-not $matchingPreset) {
    $activeTitles = ($sd3Processes | ForEach-Object { $_.MainWindowTitle } | Where-Object { $_ }) -join '; '
    throw "Wrong SD3 preset is active. Expected Greg Hybrid r15 MegaKit v23; active: '$activeTitles'."
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
    '--relative-outlier-db', '12.0',
    '--confirm-capture',
    '--confirm-preset-loaded'
)

if ($Mode -eq 'Targeted') {
    foreach ($selector in @(
        'tom2.electronic',
        'rim1.rimshot',
        'snare1.metalcore_edge',
        'snare1.deftones',
        'snare2.deftones',
        'snare1.deftones_edge',
        'rim2.rimshot',
        'rim2.cross',
        'snare1.sleep',
        'snare2.sleep',
        'snare1.sleep_edge',
        'rim_sleep.rimshot',
        'rim_sleep.cross',
        'snare_layer.deftones_sd02',
        'snare_layer.deftones_sd30',
        'snare_layer.sleep_snare8',
        'snare_layer.sleep_snare7',
        'tom1.sleep',
        'tom2.sleep',
        'tom3.sleep',
        'tom4.sleep',
        'stack.progressive_custom',
        'hh.edge_half',
        'hh.edge_closed'
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
