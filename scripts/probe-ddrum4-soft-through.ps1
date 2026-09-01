[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $MidiInput = 'UMC404HD 192k MIDI In',
    [string] $MidiOutput = 'UMC404HD 192k MIDI Out',
    [ValidateRange(1, 16)] [int] $Channel = 12,
    [ValidateRange(0, 127)] [int] $Note = 127,
    [ValidateRange(1, 1000)] [int] $Count = 100,
    [ValidateRange(1, 1000)] [int] $WindowMs = 100,
    [string] $Report = '',
    [switch] $Run,
    [switch] $ConfirmIsolatedTopology
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The project-local Python environment is missing. Run scripts\bootstrap.ps1 first.'
}
if ([string]::IsNullOrWhiteSpace($Report)) {
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $Report = Join-Path $repoRoot "local\diagnostics\ddrum4-soft-through-$stamp.json"
}
$reportPath = [IO.Path]::GetFullPath($Report)

Write-Output 'Required isolated topology:'
Write-Output '  1. Disconnect Arduino MIDI OUT from DDrum4 MIDI IN.'
Write-Output '  2. Connect UMC MIDI OUT directly to DDrum4 MIDI IN.'
Write-Output '  3. Keep DDrum4 MIDI OUT -> merger/Arduino IN -> hardware THRU -> UMC MIDI IN.'
Write-Output '  4. Set DDrum4 Local Off, C12 and aftertouch ON; leave every pad untouched.'
Write-Output "Probe: $Count repetitions each of positive Note On, velocity-zero Note On and poly-aftertouch on C$Channel/note $Note."
Write-Output "Report: $reportPath"
if (-not $Run) {
    Write-Output 'Preview only: no MIDI port was opened. Rerun with -Run -ConfirmIsolatedTopology after the cable swap.'
    exit 0
}
if (-not $ConfirmIsolatedTopology) {
    throw '-ConfirmIsolatedTopology is required because an Arduino return connection could create a MIDI loop.'
}
if (-not $PSCmdlet.ShouldProcess($reportPath, "Transmit the bounded isolated DDrum4 soft-through probe")) {
    exit 0
}
& $python -m midi_lab.cli ddrum4-echo-probe `
    --midi-input $MidiInput --midi-output $MidiOutput `
    --channel $Channel --note $Note --count $Count --window-ms $WindowMs `
    --report $reportPath --confirm-isolated-topology --send
if ($LASTEXITCODE -ne 0) { throw "DDrum4 echo probe failed with exit code $LASTEXITCODE" }
$result = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
Write-Output "Conclusion: $($result.summary.conclusion)"
Write-Output "Exact returns: $($result.summary.exact_return_total)/$($result.summary.sent_total); transformed: $($result.summary.transformed_return_total)."
$result.summary.verdict_by_type.PSObject.Properties | ForEach-Object {
    $kind = $_.Name
    Write-Output "  $kind : $($_.Value) ($($result.summary.exact_returns_by_type.$kind)/$($result.summary.sent_by_type.$kind) exact)"
}
