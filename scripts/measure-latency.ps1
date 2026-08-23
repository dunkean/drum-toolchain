[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [ValidateSet('Prepare', 'Validate', 'Analyze')] [string] $Mode,
    [Parameter(Mandatory = $true)] [string] $Matrix,
    [Parameter(Mandatory = $true)] [string] $OutputDirectory,
    [string] $MidiLab = 'midi-lab'
)

$ErrorActionPreference = 'Stop'
$matrixPath = Resolve-Path -LiteralPath $Matrix
$document = Get-Content -LiteralPath $matrixPath -Raw | ConvertFrom-Json
if ($document.kind -ne 'latency-matrix' -or $document.schema_version -ne 1) {
    throw 'Expected a latency-matrix document with schema_version 1.'
}
$runs = @($document.runs)
if (-not $runs.Count) { throw 'The latency matrix contains no runs.' }
$ids = @($runs | ForEach-Object { [string]$_.run_id })
$duplicates = @($ids | Group-Object | Where-Object Count -gt 1 | ForEach-Object Name)
if ($ids -contains '' -or $duplicates.Count) { throw 'Every latency run needs a unique, non-empty run_id.' }

$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
foreach ($run in $runs) {
    $runId = [string]$run.run_id
    if ($runId.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "run_id is not a safe file name: $runId"
    }
    $runPath = Join-Path $outputRoot "$runId.json"
    $analysisPath = Join-Path $outputRoot "$runId.analysis.json"
    if ($Mode -eq 'Prepare') {
        $arguments = @(
            'latency-prepare', '--output', $runPath, '--run-id', $runId,
            '--source', [string]$run.source, '--renderer', [string]$run.renderer,
            '--note', [string]$run.note, '--wiring', [string]$run.wiring,
            '--count', [string]$run.count, '--interval-ms', [string]$run.interval_ms
        )
        if (-not [string]::IsNullOrWhiteSpace([string]$run.profile)) { $arguments += @('--profile', [string]$run.profile) }
        if ($null -ne $run.sample_rate) { $arguments += @('--sample-rate', [string]$run.sample_rate) }
        if ($null -ne $run.buffer_frames) { $arguments += @('--buffer-frames', [string]$run.buffer_frames) }
        $target = $runPath
        $operation = 'Prepare an empty, non-overwriting latency run document'
    } elseif ($Mode -eq 'Validate') {
        if (-not (Test-Path -LiteralPath $runPath)) { throw "Latency run is missing: $runPath" }
        $arguments = @('latency-validate', $runPath)
        $target = $runPath
        $operation = 'Validate latency run document'
    } else {
        if (-not (Test-Path -LiteralPath $runPath)) { throw "Measured latency run is missing: $runPath" }
        $arguments = @('latency-analyze', $runPath, '--output', $analysisPath)
        $target = $analysisPath
        $operation = 'Analyze measured latency run without overwriting an existing analysis'
    }
    if (-not $PSCmdlet.ShouldProcess($target, $operation)) { continue }
    & $MidiLab @arguments
    if ($LASTEXITCODE -ne 0) { throw "midi-lab failed for latency run '$runId' with exit code $LASTEXITCODE" }
}

Write-Output "$Mode completed for $($runs.Count) declared latency run(s)."
if ($Mode -eq 'Prepare') {
    Write-Output 'Prepared files contain no observations. Acquisition remains an explicit external hardware step before Validate/Analyze.'
}
