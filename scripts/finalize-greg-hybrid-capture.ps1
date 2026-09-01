[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string] $RunDirectory = '',
    [string] $Project = '',
    [string] $MegaKitPlan = '',
    [switch] $ConfirmCompositeCapture,
    [switch] $ConfirmMegaKitMidiMap
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RunDirectory)) { $RunDirectory = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v23' }
if ([string]::IsNullOrWhiteSpace($Project)) { $Project = Join-Path $repoRoot 'profiles\projects\metalcore-r15-chain-simulator.yaml' }
if ([string]::IsNullOrWhiteSpace($MegaKitPlan)) { $MegaKitPlan = Join-Path $repoRoot 'profiles\sd3\metalcore-r15-megakit-plan.yaml' }
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$run = (Resolve-Path -LiteralPath $RunDirectory).Path
$projectPath = (Resolve-Path -LiteralPath $Project).Path
$planPath = (Resolve-Path -LiteralPath $MegaKitPlan).Path
$campaign = Join-Path $run 'campaign.json'
$session = Join-Path $run 'capture-session.json'
$library = Join-Path $run 'library.json'
$raw = Join-Path $run 'raw-wav'
$reports = Join-Path $run 'reports'
$composites = Join-Path $run 'drumgizmo-composite-wav'
$kit = Join-Path $run 'drumgizmo-kit'
$rigBuild = Join-Path $repoRoot 'build\metalcore-r15-chain-simulator'
$noteMap = Join-Path $rigBuild 'drumgizmo-midimap.json'

foreach ($path in @($campaign, $session, $library, $planPath, $projectPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required finalization input is missing: $path" }
}
$campaignContract = (Get-Content -LiteralPath $campaign -Raw | ConvertFrom-Json).capture_session_sha256
$currentSessionHash = (Get-FileHash -LiteralPath $session -Algorithm SHA256).Hash.ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($campaignContract) -or $campaignContract -ne $currentSessionHash) {
    throw 'capture-session.json differs from the immutable MIDI/audio contract frozen in campaign.json.'
}
$progressJson = & $python -c "import json,sys; from pathlib import Path; from control_center.campaign import Sd3CaptureCampaign; p=Path(sys.argv[1]); q=Sd3CaptureCampaign.read(p).progress(p); print(json.dumps({'captured':q.captured_takes,'total':q.total_takes,'calibration':q.calibration_status}))" $run
if ($LASTEXITCODE -ne 0) { throw 'Could not read capture campaign progress.' }
$progress = $progressJson | ConvertFrom-Json
if ($progress.captured -ne $progress.total -or $progress.calibration -ne 'technical-pass-user-mix-review-required') {
    throw "Full capture is not ready: $($progress.captured)/$($progress.total), calibration=$($progress.calibration)"
}

& $python -m drum_sampler.cli audit-quality --library $library --audio-root $raw `
    --output (Join-Path $reports 'quality.json') --session $session `
    --expected-sample-rate 48000 --expected-channels 2
if ($LASTEXITCODE -ne 0) { throw "Full-capture quality gate failed with exit code $LASTEXITCODE" }

if (-not $ConfirmCompositeCapture -or -not $ConfirmMegaKitMidiMap) {
    throw 'Composite capture requires -ConfirmCompositeCapture and -ConfirmMegaKitMidiMap after checking Kit_Metalcore_MidiMapping_Capture_V1 in SD3.'
}
$sd3Check = & $python -c "import json,sys; from control_center.service import active_sd3_window_titles,verify_active_sd3_preset; d=json.load(open(sys.argv[1],encoding='utf-8')); t=' | '.join(active_sd3_window_titles()); verify_active_sd3_preset(d,t); print(t)" $campaign
if ($LASTEXITCODE -ne 0) { throw 'The active SD3 window does not match the frozen v23 campaign preset.' }
Write-Output "Verified active SD3 window: $sd3Check"

if ($PSCmdlet.ShouldProcess($composites, 'Send the 42 simultaneous layer chords to SD3 and record their stereo audio')) {
    & $python -m drum_sampler.cli capture-composites --session $session --megakit-plan $planPath `
        --output-directory $composites --quality-report (Join-Path $reports 'composite-quality.json') `
        --confirm-capture
    if ($LASTEXITCODE -ne 0) { throw "Composite capture/quality gate failed with exit code $LASTEXITCODE" }
}

& (Join-Path $PSScriptRoot 'build-rig.ps1') -Project $projectPath -Output $rigBuild -Replace -Confirm:$false | Write-Output
if (-not (Test-Path -LiteralPath $noteMap -PathType Leaf)) { throw "Compiled DrumGizmo note map is missing: $noteMap" }
if (Test-Path -LiteralPath $kit) {
    throw "DrumGizmo output already exists: $kit. Archive it explicitly before generating a new immutable export."
}
& $python -m drum_sampler.cli export-drumgizmo --library $library --audio-root $raw `
    --output-directory $kit --note-map $noteMap --megakit-plan $planPath `
    --title 'Greg Hybrid r15 MegaKit v23' --report (Join-Path $reports 'drumgizmo-export.json')
if ($LASTEXITCODE -ne 0) { throw "DrumGizmo export failed with exit code $LASTEXITCODE" }
& $python -m drum_sampler.cli validate-drumgizmo --kit-directory $kit `
    --report (Join-Path $reports 'drumgizmo-validation.json')
if ($LASTEXITCODE -ne 0) { throw "DrumGizmo internal validation failed with exit code $LASTEXITCODE" }

Write-Output "Finalized immutable SD3 capture library: $library"
Write-Output "Finalized and internally validated DrumGizmo kit: $kit"
Write-Output 'No Arduino, DDTi, eDRUMin, or DDrum4 write/flash operation was executed.'
