[CmdletBinding()]
param(
    [switch] $ConfirmInstall,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
if (-not $ConfirmInstall) {
    throw 'This writes a user SD3 EdrumPresets file. Pass -ConfirmInstall after closing the MIDI Mapping preset menu.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$profile = Join-Path $repoRoot 'profiles\sd3\greg-hybrid-standard-edrum-map.yaml'
$generated = Join-Path $repoRoot 'build\sd3\Greg_Hybrid_Standard_SD3_Kits'
$presetDirectory = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Toontrack\Superior3\EdrumPresets'
$installed = Join-Path $presetDirectory 'Greg_Hybrid_Standard_SD3_Kits'

foreach ($required in ($python, $profile)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required SD3 map input is missing: $required"
    }
}
if ((Test-Path -LiteralPath $installed -PathType Leaf) -and -not $Force) {
    throw "SD3 map already exists: $installed. Pass -Force to replace it from the reviewed profile."
}

& $python -m midi_lab.cli sd3-build-edrum-map --profile $profile --output $generated --force
if ($LASTEXITCODE -ne 0) { throw "SD3 e-drum map generation failed with exit code $LASTEXITCODE." }
New-Item -ItemType Directory -Path $presetDirectory -Force | Out-Null
Copy-Item -LiteralPath $generated -Destination $installed -Force
$generatedHash = (Get-FileHash -LiteralPath $generated -Algorithm SHA256).Hash
$installedHash = (Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash
if ($generatedHash -ne $installedHash) {
    throw 'Installed SD3 e-drum map does not match the generated file.'
}
Write-Output "Installed SD3 e-drum map: $installed"
Write-Output "SHA-256: $($installedHash.ToLowerInvariant())"
