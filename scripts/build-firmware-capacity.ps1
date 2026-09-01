param(
    [string]$ProjectMapping,
    [string]$Report
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$firmwareRoot = Join-Path $repoRoot 'firmware\ddrum4-midi-bridge'
if ([string]::IsNullOrWhiteSpace($ProjectMapping)) {
    $ProjectMapping = Join-Path $repoRoot 'build\metalcore-r15-chain-simulator\firmware-project-mapping.json'
}
if ([string]::IsNullOrWhiteSpace($Report)) {
    $Report = Join-Path $repoRoot 'build\firmware-capacity\uno-capacity-report.json'
}
$ProjectMapping = [System.IO.Path]::GetFullPath($ProjectMapping)
$Report = [System.IO.Path]::GetFullPath($Report)
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$pio = Join-Path $repoRoot '.venv\Scripts\pio.exe'
$generator = Join-Path $firmwareRoot 'tools\generate_mapping.py'
$generatedDirectory = Join-Path $firmwareRoot 'generated\capacity'
$header = Join-Path $generatedDirectory 'generated_capacity_mapping.h'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Workspace Python is missing: $python"
}
if (-not (Test-Path -LiteralPath $pio -PathType Leaf)) {
    throw "Workspace PlatformIO is missing: $pio"
}
if (-not (Test-Path -LiteralPath $ProjectMapping -PathType Leaf)) {
    throw "Firmware project mapping is missing: $ProjectMapping"
}

New-Item -ItemType Directory -Force -Path $generatedDirectory | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Report) | Out-Null
$mapping = Get-Content -LiteralPath $ProjectMapping -Raw | ConvertFrom-Json
$outputChannel = [int]$mapping.ddrum4_output_channel

& $python $generator --project-mapping $ProjectMapping --capacity-estimate `
    --output-channel $outputChannel --output $header
if ($LASTEXITCODE -ne 0) {
    throw "Capacity header generation failed with exit code $LASTEXITCODE"
}

$headerText = Get-Content -LiteralPath $header -Raw
if ($headerText -notmatch 'DDRUM_CAPACITY_ESTIMATE_ONLY' -or
        $headerText -notmatch 'must never be used by a flashable firmware environment') {
    throw 'Generated capacity header is missing its non-flashable compile guard'
}

$buildLines = @(& $pio run -d $firmwareRoot -e uno_capacity 2>&1 | ForEach-Object { [string]$_ })
$buildLines | ForEach-Object { Write-Output $_ }
if ($LASTEXITCODE -ne 0) {
    throw "Uno capacity build failed with exit code $LASTEXITCODE"
}
$buildText = $buildLines -join "`n"
$ram = [regex]::Match($buildText, 'RAM:\s+\[[^\]]+\]\s+([0-9.]+)%\s+\(used\s+(\d+)\s+bytes\s+from\s+(\d+)\s+bytes\)')
$flash = [regex]::Match($buildText, 'Flash:\s+\[[^\]]+\]\s+([0-9.]+)%\s+\(used\s+(\d+)\s+bytes\s+from\s+(\d+)\s+bytes\)')
if (-not $ram.Success -or -not $flash.Success) {
    throw 'PlatformIO succeeded but its Uno memory summary could not be parsed'
}

function Get-GeneratedEntryCount([string]$TypeName, [string]$CountName) {
    $declared = [regex]::Match($headerText, "constexpr size_t $CountName = (\d+);")
    if ($declared.Success) { return [int]$declared.Groups[1].Value }
    $match = [regex]::Match(
        $headerText,
        "const $TypeName [A-Z_]+\[\] PROGMEM = \{(?<body>.*?)\r?\n\};",
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )
    if (-not $match.Success) { return 0 }
    return @($match.Groups['body'].Value -split "\r?\n" | Where-Object { $_ -match '^\s*\{' }).Count
}

$reportDocument = [ordered]@{
    format = 'ddrum4-firmware-capacity-report/v1'
    environment = 'uno_capacity'
    flashable = $false
    source_mapping = $ProjectMapping
    source_sha256 = [string]$mapping.source_sha256
    generated_header = $header
    generated_header_sha256 = (Get-FileHash -LiteralPath $header -Algorithm SHA256).Hash.ToLowerInvariant()
    tables = [ordered]@{
        state_routes = Get-GeneratedEntryCount 'StateRoute' 'STATE_ROUTE_COUNT'
        native_controls = Get-GeneratedEntryCount 'NativeControlRoute' 'NATIVE_CONTROL_COUNT'
        state_actions = Get-GeneratedEntryCount 'DdrumStateAction' 'STATE_ACTION_COUNT'
        pressure_routes = Get-GeneratedEntryCount 'PressureRoute' 'PRESSURE_ROUTE_COUNT'
        hihat_hit_routes = Get-GeneratedEntryCount 'HihatHitRoute' 'HIHAT_HIT_ROUTE_COUNT'
    }
    memory = [ordered]@{
        ram_used_bytes = [int]$ram.Groups[2].Value
        ram_total_bytes = [int]$ram.Groups[3].Value
        ram_percent = [double]::Parse($ram.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
        flash_used_bytes = [int]$flash.Groups[2].Value
        flash_total_bytes = [int]$flash.Groups[3].Value
        flash_percent = [double]::Parse($flash.Groups[1].Value, [Globalization.CultureInfo]::InvariantCulture)
    }
    safety = [ordered]@{
        guarded_header = $true
        upload_command = 'reject_capacity_upload.py'
        hardware_io = 'not opened'
    }
}
$reportDocument | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Report -Encoding utf8
Write-Output "Capacity report: $Report"
