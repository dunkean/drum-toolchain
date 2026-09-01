[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $Campaign = '',
    [string] $InputPort = '',
    [string] $TraceId = '',
    [ValidateRange(0.5, 60.0)] [double] $Seconds = 5.0,
    [switch] $Capture,
    [switch] $ReplaceTrace
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
if (-not (Test-Path -LiteralPath $sourceProject -PathType Leaf)) {
    throw "Campaign source project not found: $sourceProject"
}
$actualSourceHash = (Get-FileHash -LiteralPath $sourceProject -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedSourceHash = ([string]$plan.source_sha256).ToLowerInvariant()
if ($actualSourceHash -ne $expectedSourceHash) {
    throw 'The rig project changed after this campaign was created. Create a new campaign; do not mix traces from different project hashes.'
}

$requests = @($plan.trace_requests | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.trace) })
if (-not $requests.Count) { throw 'The campaign contains no automatically capturable trace requests.' }
$selected = $null
if (-not [string]::IsNullOrWhiteSpace($TraceId)) {
    $matches = @($requests | Where-Object { [string]$_.id -eq $TraceId })
    if ($matches.Count -ne 1) { throw "TraceId must match exactly one campaign request: $TraceId" }
    $selected = $matches[0]
} else {
    $selected = $requests | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $campaignPath ([string]$_.trace)) -PathType Leaf)
    } | Select-Object -First 1
}
if ($null -eq $selected) {
    Write-Output 'All automatically capturable traces already exist. Run measurement-review next.'
    exit 0
}

$tracePath = [IO.Path]::GetFullPath((Join-Path $campaignPath ([string]$selected.trace)))
$campaignPrefix = $campaignPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $tracePath.StartsWith($campaignPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing a trace path outside the campaign: $tracePath"
}
$exists = Test-Path -LiteralPath $tracePath -PathType Leaf
if ($exists -and -not $ReplaceTrace) {
    throw "Trace already exists: $tracePath. Pass -ReplaceTrace only after reviewing the existing capture."
}

$matcher = $selected.matcher | ConvertTo-Json -Compress
$messageType = if ($selected.PSObject.Properties.Name -contains 'message_type') {
    [string]$selected.message_type
} elseif ($null -ne $selected.matcher -and
        $selected.matcher.PSObject.Properties.Name -contains 'type') {
    [string]$selected.matcher.type
} else {
    ''
}
Write-Output "Next isolated trace: $($selected.id)"
Write-Output "Source: $($selected.source)  Physical: $($selected.physical)"
Write-Output "Expected matcher: $matcher"
Write-Output "Destination: $tracePath"
$instruction = switch ($messageType) {
    'poly_aftertouch' { 'Strike this pad/zone once, keep it active, then choke it once; no other pad may be active.' }
    'program_change' { "Select only this DDrum4 Scene/Palette control once (expected Program $([int]$selected.matcher.program)); do not strike a pad." }
    'cc' { "Move only the declared controller through its complete physical range (expected CC $([int]$selected.matcher.cc)); do not strike another pad." }
    'note_range' { 'Sweep every position of this pad/zone so every declared contiguous Note code is observed; do not strike another pad.' }
    default { 'Strike only this pad/zone once; do not strike another pad.' }
}
Write-Output "Action: $instruction"
if (-not $Capture) {
    Write-Output 'Preview only: no MIDI port was opened. Rerun with -InputPort <exact-name> -Capture when ready.'
    exit 0
}
if ([string]::IsNullOrWhiteSpace($InputPort)) {
    throw '-InputPort is required with -Capture and must uniquely identify the observed raw MIDI input.'
}
if (-not $PSCmdlet.ShouldProcess($tracePath, "Listen to '$InputPort' for $Seconds seconds and capture one isolated MIDI trace")) {
    exit 0
}
$traceDirectory = Split-Path -Parent $tracePath
$traceStem = [IO.Path]::GetFileNameWithoutExtension($tracePath)
$capturePath = Join-Path $traceDirectory (".$traceStem.capture-" + [guid]::NewGuid().ToString('N') + '.jsonl')
$backupPath = $null
try {
    & $python -m midi_lab.cli record --input $InputPort --seconds $Seconds --output $capturePath
    if ($LASTEXITCODE -ne 0) { throw "MIDI trace capture failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath $capturePath -PathType Leaf)) {
        throw "MIDI trace recorder did not create its bounded capture: $capturePath"
    }
    if ($exists) {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
        $backupPath = Join-Path $traceDirectory ("$traceStem.replaced-$stamp.jsonl")
        if (Test-Path -LiteralPath $backupPath) {
            throw "Refusing to overwrite an archived trace: $backupPath"
        }
        Move-Item -LiteralPath $tracePath -Destination $backupPath
    }
    Move-Item -LiteralPath $capturePath -Destination $tracePath
} catch {
    if ($null -ne $backupPath -and (Test-Path -LiteralPath $backupPath -PathType Leaf) -and
            -not (Test-Path -LiteralPath $tracePath)) {
        Move-Item -LiteralPath $backupPath -Destination $tracePath
        $backupPath = $null
    }
    if (Test-Path -LiteralPath $capturePath -PathType Leaf) {
        $failedPath = Join-Path $traceDirectory ("$traceStem.failed-" + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.jsonl')
        Move-Item -LiteralPath $capturePath -Destination $failedPath
        throw "$($_.Exception.Message) Partial capture retained for inspection: $failedPath"
    }
    throw
}
if ($null -ne $backupPath) {
    Write-Output "Previous trace archived: $backupPath"
}

$reviewText = & $python -m control_center.cli measurement-review $campaignPath --json
$reviewExitCode = $LASTEXITCODE
try { $review = $reviewText | ConvertFrom-Json } catch { throw "Could not parse measurement review: $reviewText" }
$row = $review.rows | Where-Object { [string]$_.id -eq [string]$selected.id } | Select-Object -First 1
if ($null -eq $row) { throw "Measurement review did not contain $($selected.id)" }
if ([string]$row.status -ne 'observed') {
    $reason = if ($null -ne $row.reason) { [string]$row.reason } else { 'capture was not an isolated matching event' }
    throw "Trace retained for inspection but not accepted: $($row.status) — $reason"
}
if ([string]$row.message_type -eq 'note_range') {
    Write-Output "Accepted positional sweep: $($selected.id), channel $($row.channel), notes $($row.note_range[0])..$($row.note_range[1])."
} else {
    Write-Output "Accepted isolated trace: $($selected.id), channel $($row.channel), data1 $($row.data1)."
}
if ($reviewExitCode -eq 0) {
    Write-Output 'Campaign complete. Run promote-live only after reviewing every observed address and the exact port names.'
} else {
    Write-Output 'Campaign still incomplete. Rerun this script without -TraceId to preview the next missing trace.'
}
