[CmdletBinding()]
param(
    [ValidatePattern('^COM[0-9]+$')]
    [string]$Port = 'COM3',
    [Parameter(Mandatory)] [string]$ProjectMapping,
    [string]$SourceContract = '',
    [string]$DDTiReceipt = '',
    [string]$EDruminReceipt = '',
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repoRoot 'firmware\ddrum4-midi-bridge'
$mappingPath = [IO.Path]::GetFullPath($ProjectMapping)
if (-not (Test-Path -LiteralPath $mappingPath -PathType Leaf)) {
    throw "Firmware project mapping does not exist: $mappingPath"
}
$mapping = Get-Content -LiteralPath $mappingPath -Raw | ConvertFrom-Json
if ($mapping.format -ne 'ddrum4-firmware-project-mapping-plan/v1' -or
    $mapping.deployment -ne 'live' -or $mapping.status -ne 'ready' -or
    $mapping.hardware_flash -ne 'ready') {
    throw 'Flash requires firmware-project-mapping.json with deployment=live, status=ready, hardware_flash=ready.'
}
if ($mapping.validation_stage -notin @('post-flash-validation-pending', 'hardware-verified')) {
    throw 'Flash mapping must declare validation_stage=post-flash-validation-pending or hardware-verified.'
}
if ([string]::IsNullOrWhiteSpace([string]$mapping.source_contract_sha256)) {
    throw 'Firmware mapping has no source_contract_sha256; rebuild it with the current rig compiler.'
}
if ([string]::IsNullOrWhiteSpace($SourceContract)) {
    $SourceContract = Join-Path (Split-Path -Parent $mappingPath) 'source-note-contract.yaml'
}
$contractPath = [IO.Path]::GetFullPath($SourceContract)
if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
    throw "Compiled source contract does not exist: $contractPath"
}
$contractText = Get-Content -LiteralPath $contractPath -Raw
$contractMatch = [regex]::Match($contractText, '(?m)^source_contract_sha256:\s*([0-9a-f]{64})\s*$')
if (-not $contractMatch.Success -or $contractMatch.Groups[1].Value -ne $mapping.source_contract_sha256) {
    throw 'Source contract fingerprint does not match the live firmware mapping.'
}

if (-not $BuildOnly) {
    foreach ($receiptPath in @($DDTiReceipt, $EDruminReceipt)) {
        if ([string]::IsNullOrWhiteSpace($receiptPath) -or -not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
            throw 'Hardware flash requires existing -DDTiReceipt and -EDruminReceipt files.'
        }
    }
    $ddti = Get-Content -LiteralPath $DDTiReceipt -Raw | ConvertFrom-Json
    if ($ddti.kind -ne 'greg-hybrid-ddti-configuration-receipt/v1' -or $ddti.status -ne 'verified' -or
        $ddti.source_contract_sha256 -ne $mapping.source_contract_sha256 -or
        $ddti.candidate_sha256 -ne $ddti.readback_sha256) {
        throw 'DDTi receipt is not a verified readback for this exact source contract.'
    }
    $edrumin = Get-Content -LiteralPath $EDruminReceipt -Raw | ConvertFrom-Json
    if ($edrumin.kind -ne 'greg-hybrid-edrumin-configuration-receipt/v1' -or
        $edrumin.status -ne 'user-confirmed' -or
        $edrumin.source_contract_sha256 -ne $mapping.source_contract_sha256) {
        throw 'eDRUMin receipt is not a user-confirmed snapshot for this exact source contract.'
    }
    $modulePlan = Get-Content -LiteralPath (Join-Path $repoRoot 'profiles\physical\greg-hybrid-module-configuration.yaml') -Raw
    if ($modulePlan -notmatch '(?ms)^\s{2}ddrum4:.*?^\s{4}status:\s*user-confirmed\s*$') {
        throw 'DDrum4 module configuration is not user-confirmed in the module plan.'
    }
}
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) {
    $venvPython
} else {
    (Get-Command python -ErrorAction Stop).Source
}

$header = Join-Path $project 'include\generated_mapping.h'
& $python (Join-Path $project 'tools\generate_mapping.py') --project-mapping $mappingPath `
    --output-channel ([int]$mapping.ddrum4_output_channel) --output $header
if ($LASTEXITCODE -ne 0) { throw 'Live firmware mapping header generation failed.' }
$headerSha256 = (Get-FileHash -LiteralPath $header -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Building DDrum4 MIDI bridge from live mapping $($mapping.source_sha256); header $headerSha256."
Push-Location $project
try {
    & $python -m platformio run -e uno
    if ($LASTEXITCODE -ne 0) { throw "Uno build failed with exit code $LASTEXITCODE" }
    if (-not $BuildOnly) {
        Write-Host "Flashing $Port. The MIDI shield must be in PGM mode."
        $permitDirectory = Join-Path $repoRoot 'local\flash'
        New-Item -ItemType Directory -Path $permitDirectory -Force | Out-Null
        $permitPath = Join-Path $permitDirectory ("reviewed-upload-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $permit = [ordered]@{
            kind = 'ddrum-reviewed-upload-permit/v1'
            status = 'authorized'
            expires_at = (Get-Date).ToUniversalTime().AddMinutes(10).ToString('o')
            mapping_path = $mappingPath
            mapping_sha256 = (Get-FileHash -LiteralPath $mappingPath -Algorithm SHA256).Hash.ToLowerInvariant()
            header_path = $header
            header_sha256 = $headerSha256
            source_contract_sha256 = $mapping.source_contract_sha256
        }
        [IO.File]::WriteAllText($permitPath, (($permit | ConvertTo-Json -Depth 10) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
        $previousPermit = $env:DDRUM_REVIEWED_UPLOAD_PERMIT
        $env:DDRUM_REVIEWED_UPLOAD_PERMIT = $permitPath
        try {
            & $python -m platformio run -e uno --target upload --upload-port $Port
            if ($LASTEXITCODE -ne 0) { throw "Uno upload failed with exit code $LASTEXITCODE" }
        } finally {
            $env:DDRUM_REVIEWED_UPLOAD_PERMIT = $previousPermit
            Remove-Item -LiteralPath $permitPath -Force -ErrorAction SilentlyContinue
        }
        Write-Host 'Flash verified. Move the shield switch to RUN before MIDI use.'
    }
} finally {
    Pop-Location
}
