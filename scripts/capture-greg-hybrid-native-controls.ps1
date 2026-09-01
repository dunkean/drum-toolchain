[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $Campaign = '',
    [string] $InputPort = '',
    [ValidateRange(30.0, 300.0)] [double] $Seconds = 120.0,
    [switch] $Capture,
    [switch] $ConfirmSequence
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The project-local Python environment is missing. Run scripts\bootstrap.ps1 first.'
}
if ([string]::IsNullOrWhiteSpace($Campaign)) {
    $Campaign = Join-Path $repoRoot 'build\measurements\greg-hybrid-r15-v23-r10'
}
$campaignPath = [IO.Path]::GetFullPath($Campaign)
$planPath = Join-Path $campaignPath 'live-measurement-plan.json'
if (-not (Test-Path -LiteralPath $planPath -PathType Leaf)) {
    throw "Live measurement plan not found: $planPath"
}
$plan = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
$sourceProject = [IO.Path]::GetFullPath([string]$plan.source_project)
$actualSourceHash = (Get-FileHash -LiteralPath $sourceProject -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualSourceHash -ne ([string]$plan.source_sha256).ToLowerInvariant()) {
    throw 'The rig project changed after this campaign was created. Create a new campaign first.'
}
$requests = @($plan.trace_requests | Where-Object {
    [string]$_.message_type -eq 'program_change' -and [string]$_.id -like 'native.*'
})
if (-not $requests.Count) { throw 'The campaign declares no native Program Change sequence.' }

Write-Output "Native DDrum4 panel sequence — $($requests.Count) actions, in this exact order:"
$sceneLabels = @{
    ddrum_program_metalcore = 'KIT 1 (Metalcore)'
    ddrum_program_sleep_token = 'KIT 5 (Sleep Token)'
    ddrum_program_deftones = 'KIT 6 (Deftones)'
    ddrum_program_dnb = 'KIT 7 (DnB)'
    ddrum_program_industrial = 'KIT 9 (Industrial)'
    ddrum_program_electro = 'KIT 11 (Electro)'
}
for ($index = 0; $index -lt $requests.Count; $index++) {
    $request = $requests[$index]
    $program = [int]$request.matcher.program
    $name = ([string]$request.id).Substring(7)
    $label = if ($sceneLabels.ContainsKey($name)) {
        $sceneLabels[$name]
    } elseif ($name -match '^ddrum_(kick|snare|toms|perc)_palette_(1|2|3|4|5|kit)$') {
        ('{0} palette {1}' -f $Matches[1].ToUpperInvariant(), $Matches[2].ToUpperInvariant())
    } else {
        $name
    }
    Write-Output ('{0,2}. PC {1,3}  {2}' -f ($index + 1), $program, $label)
}
Write-Output ''
if (-not $Capture) {
    Write-Output 'Preview only: no MIDI port was opened. Rerun with -InputPort <UMC input> -Capture -ConfirmSequence.'
    exit 0
}
if ([string]::IsNullOrWhiteSpace($InputPort)) {
    throw '-InputPort is required with -Capture.'
}
if (-not $ConfirmSequence) {
    throw '-ConfirmSequence is required: be ready to perform every listed panel action once and in order.'
}
$batchDirectory = Join-Path $campaignPath 'raw-sequences'
$batchPath = Join-Path $batchDirectory 'ddrum4-native-controls.jsonl'
if (Test-Path -LiteralPath $batchPath) {
    throw "Sequence capture already exists and will not be overwritten: $batchPath"
}
if (-not $PSCmdlet.ShouldProcess(
        $batchPath,
        "Listen receive-only to '$InputPort' for $Seconds seconds, then validate and split $($requests.Count) controls")) {
    exit 0
}
New-Item -ItemType Directory -Path $batchDirectory -Force | Out-Null
$temporary = Join-Path $batchDirectory ('.ddrum4-native-controls.capture-' + [guid]::NewGuid().ToString('N') + '.jsonl')
try {
    Write-Output "Listening receive-only for $Seconds seconds. Perform the sequence now."
    & $python -m midi_lab.cli record --input $InputPort --seconds $Seconds --output $temporary
    if ($LASTEXITCODE -ne 0) { throw "MIDI recorder failed with exit code $LASTEXITCODE" }
    Move-Item -LiteralPath $temporary -Destination $batchPath
    & $python -m control_center.cli measurement-import-native-sequence $campaignPath $batchPath
    if ($LASTEXITCODE -ne 0) {
        throw 'The sequence did not match exactly. The raw batch was retained for inspection; no isolated proof was published.'
    }
} catch {
    $failed = Join-Path $batchDirectory ('ddrum4-native-controls.failed-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.jsonl')
    if (Test-Path -LiteralPath $temporary) {
        Move-Item -LiteralPath $temporary -Destination $failed
    } elseif (Test-Path -LiteralPath $batchPath) {
        Move-Item -LiteralPath $batchPath -Destination $failed
    }
    throw
}
Write-Output "Accepted all $($requests.Count) native controls. The campaign now contains their isolated evidence."
