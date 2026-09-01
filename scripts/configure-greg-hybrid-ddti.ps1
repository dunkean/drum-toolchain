[CmdletBinding(DefaultParameterSetName = 'Capture')]
param(
    [Parameter(ParameterSetName = 'Capture')]
    [switch] $CaptureCurrent,
    [Parameter(Mandatory, ParameterSetName = 'Apply')]
    [switch] $Apply,
    [string] $InputPort = 'TriggerIO',
    [string] $OutputPort = 'TriggerIO',
    [ValidateRange(15, 300)] [int] $Seconds = 90,
    [switch] $ConfirmWrite
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python environment is missing: $python"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$session = Join-Path $repoRoot "local\ddti\greg-hybrid-$stamp"
New-Item -ItemType Directory -Path $session -Force | Out-Null

if ($PSCmdlet.ParameterSetName -eq 'Capture') {
    $stem = Join-Path $session 'current-before-write'
    Write-Output "Listening receive-only on '$InputPort'."
    Write-Output 'On the DDTi, press FUNCTION UP and VALUE UP simultaneously now.'
    & $python -m ddti.cli dump $stem --input $InputPort --listen --seconds $Seconds --idle-seconds 5
    if ($LASTEXITCODE -ne 0) { throw "DDTi capture failed with exit code $LASTEXITCODE." }
    & $python -m ddti.cli transfer-plan ($stem + '.syx')
    if ($LASTEXITCODE -ne 0) { throw 'The DDTi did not return a complete validated dump.' }
    Write-Output "Validated current dump: $($stem + '.syx')"
    exit 0
}

if (-not $ConfirmWrite) {
    throw 'Apply requires -ConfirmWrite before a fresh same-session dump can be captured and staged.'
}
$preWriteStem = Join-Path $session 'current-before-write'
Write-Output "Apply is armed, but no write occurs until a fresh dump is captured from '$InputPort'."
Write-Output 'On the DDTi, press FUNCTION UP and VALUE UP simultaneously now.'
& $python -m ddti.cli dump $preWriteStem --input $InputPort --listen --seconds $Seconds --idle-seconds 5
if ($LASTEXITCODE -ne 0) { throw 'Fresh DDTi pre-write capture failed; nothing was written.' }
& $python -m ddti.cli transfer-plan ($preWriteStem + '.syx')
if ($LASTEXITCODE -ne 0) { throw 'Fresh DDTi pre-write dump is incomplete; nothing was written.' }
$source = [IO.Path]::GetFullPath($preWriteStem + '.syx')
$template = Join-Path $repoRoot 'build\rig\metalcore-r15\ddti-role-template.yaml'
$layout = Join-Path $repoRoot 'profiles\physical\greg-hybrid-ddti-layout.yaml'
$candidate = Join-Path $session 'greg-hybrid-ddti-staged.syx'
$templateText = Get-Content -LiteralPath $template -Raw
$contractMatch = [regex]::Match($templateText, '(?m)^source_contract_sha256:\s*([0-9a-f]{64})\s*$')
if (-not $contractMatch.Success) {
    throw 'The compiled DDTi role template has no source_contract_sha256; rebuild the rig before configuration.'
}
$sourceContractSha256 = $contractMatch.Groups[1].Value

& $python -m ddti.cli apply-role-preset $source $template $layout $candidate
if ($LASTEXITCODE -ne 0) { throw 'Could not stage the Greg Hybrid DDTi role preset.' }
$planText = & $python -m ddti.cli write-plan $source $candidate
if ($LASTEXITCODE -ne 0) { throw 'The staged DDTi candidate failed confirmed-fields validation.' }
$plan = $planText | ConvertFrom-Json
$planPath = Join-Path $session 'write-plan.json'
[IO.File]::WriteAllText($planPath, (($plan | ConvertTo-Json -Depth 20) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
Write-Output "Reviewed candidate SHA-256: $($plan.candidate_sha256)"

$writeText = & $python -m ddti.cli write-config $source $candidate --output $OutputPort `
    --expected-sha256 $plan.candidate_sha256 --confirm I_AUTHORIZE_DDTI_CONFIRMED_FIELDS `
    --inter-message-ms 50
if ($LASTEXITCODE -ne 0) { throw 'DDTi confirmed-fields write failed.' }
$write = $writeText | ConvertFrom-Json
Write-Output 'Write sent. Starting mandatory receive-only readback.'
$readbackStem = Join-Path $session 'post-write-readback'
Write-Output 'On the DDTi, press FUNCTION UP and VALUE UP simultaneously now.'
& $python -m ddti.cli dump $readbackStem --input $InputPort --listen --seconds $Seconds --idle-seconds 5
if ($LASTEXITCODE -ne 0) { throw 'DDTi post-write panel dump failed; no verified receipt was created.' }
$readbackText = & $python -m ddti.cli verify-readback $candidate ($readbackStem + '.syx')
if ($LASTEXITCODE -ne 0) { throw 'DDTi post-write readback differs from the reviewed candidate.' }
$readback = $readbackText | ConvertFrom-Json
$receipt = [ordered]@{
    kind = 'greg-hybrid-ddti-configuration-receipt/v1'
    status = 'verified'
    session_id = $stamp
    source_dump = $source
    source_sha256 = $plan.source_sha256
    source_contract_sha256 = $sourceContractSha256
    candidate = $candidate
    candidate_sha256 = $plan.candidate_sha256
    output_port = $write.output_port
    sent_packet_count = $write.packet_count
    readback_dump = $readbackStem + '.syx'
    readback_sha256 = $readback.readback_sha256
    readback_packet_count = $readback.packet_count
}
$receiptPath = Join-Path $session 'verified-configuration-receipt.json'
[IO.File]::WriteAllText($receiptPath, (($receipt | ConvertTo-Json -Depth 20) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
Write-Output "DDTi configuration and readback verified: $receiptPath"
