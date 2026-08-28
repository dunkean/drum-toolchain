[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [string] $Project,
    [string] $Output = '',
    [switch] $Replace
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$projectPath = (Resolve-Path -LiteralPath $Project).Path
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $repoRoot ('build\rig\' + [IO.Path]::GetFileNameWithoutExtension($projectPath))
}
$outputPath = [IO.Path]::GetFullPath($Output)
if ((Test-Path -LiteralPath $outputPath) -and -not $Replace) {
    throw "Output already exists: $outputPath. Pass -Replace to regenerate this explicit build directory."
}
if (-not $PSCmdlet.ShouldProcess($outputPath, 'Compile offline rig artifacts')) { return }

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Join-Path $repoRoot 'packages\drum-domain\src') + ';' + (Join-Path $repoRoot 'tools\rig-compiler\src')
try {
    $arguments = @('-m', 'rig_compiler.cli', 'compile', $projectPath, '--output', $outputPath)
    if ($Replace) { $arguments += '--replace' }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Rig compilation failed with exit code $LASTEXITCODE" }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

$report = Join-Path $outputPath 'project-report.json'
if (-not (Test-Path -LiteralPath $report)) { throw "Compiler did not produce $report" }
$document = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
[ordered]@{
    project = $document.project
    deployment = $document.deployment
    output = $outputPath
    source_sha256 = $document.source_sha256
    firmware = ($document.artifacts | Where-Object name -eq 'firmware-project-mapping').status
    note = 'Offline build only: it neither opens MIDI ports nor flashes Arduino/DDTi/DDrum4.'
} | ConvertTo-Json -Depth 4
