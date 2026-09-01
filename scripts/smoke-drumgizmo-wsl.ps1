[CmdletBinding()]
param(
    [string]$KitDirectory,
    [string]$Report,
    [string]$ValidationReport,
    [string]$Distribution = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($KitDirectory)) {
    $KitDirectory = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v23\drumgizmo-kit-current-r5'
}
if ([string]::IsNullOrWhiteSpace($Report)) {
    $Report = Join-Path $repoRoot 'build\capture\greg-hybrid-r15-full-v23\reports\drumgizmo-wsl-smoke-current-r5.json'
}
$KitDirectory = [IO.Path]::GetFullPath($KitDirectory)
$Report = [IO.Path]::GetFullPath($Report)
$kitLeaf = Split-Path -Leaf $KitDirectory
$validationStem = if ($kitLeaf.StartsWith('drumgizmo-kit-', [StringComparison]::OrdinalIgnoreCase)) {
    $kitLeaf.Substring('drumgizmo-kit-'.Length)
} else {
    $kitLeaf
}
if ([string]::IsNullOrWhiteSpace($ValidationReport)) {
    if (-not $kitLeaf.StartsWith('drumgizmo-kit-', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'ValidationReport is required when KitDirectory does not use the drumgizmo-kit-* naming convention'
    }
    $ValidationReport = Join-Path (Join-Path (Split-Path -Parent $KitDirectory) 'reports') `
        "drumgizmo-validation-$validationStem.json"
}
$ValidationReport = [IO.Path]::GetFullPath($ValidationReport)
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$drumkit = Join-Path $KitDirectory 'drumkit.xml'
if (-not (Test-Path -LiteralPath $drumkit -PathType Leaf)) {
    throw "DrumGizmo drumkit.xml is missing: $drumkit"
}
if (-not (Test-Path -LiteralPath $ValidationReport -PathType Leaf)) {
    throw "Internal DrumGizmo validation report is missing: $ValidationReport"
}
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is not installed'
}

$validation = Get-Content -LiteralPath $ValidationReport -Raw | ConvertFrom-Json
& $python -m drum_sampler.cli verify-drumgizmo-manifest `
    --kit-directory $KitDirectory --report $ValidationReport
if ($LASTEXITCODE -ne 0) { throw 'DrumGizmo kit changed after internal validation' }
$drumkitSha256 = (Get-FileHash -LiteralPath $drumkit -Algorithm SHA256).Hash.ToLowerInvariant()
$midimapSha256 = (Get-FileHash -LiteralPath (Join-Path $KitDirectory 'midimap.xml') -Algorithm SHA256).Hash.ToLowerInvariant()

$portableKitDirectory = $KitDirectory -replace '\\', '/'
$wslPathLines = @(& wsl.exe -d $Distribution -- wslpath -a -u $portableKitDirectory 2>&1 |
    ForEach-Object { [string]$_ })
if ($LASTEXITCODE -ne 0 -or -not $wslPathLines) {
    throw "Could not resolve the kit path in WSL distribution ${Distribution}: $($wslPathLines -join '; ')"
}
$wslKit = ([string]($wslPathLines | Select-Object -Last 1)).Trim()
$wslDrumkit = "$wslKit/drumkit.xml"
$probeDirectory = Join-Path (Split-Path -Parent $KitDirectory) "aftertouch-probe-$validationStem"
New-Item -ItemType Directory -Force -Path $probeDirectory | Out-Null
foreach ($prefix in @('control', 'choke')) {
    Get-ChildItem -LiteralPath $probeDirectory -Filter "$prefix*.wav" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force
}
& $python -m drum_sampler.drumgizmo_probe prepare --midimap (Join-Path $KitDirectory 'midimap.xml') `
    --output-directory $probeDirectory --instrument crash1__bow
if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the DrumGizmo aftertouch proof MIDI files' }
$portableProbeDirectory = $probeDirectory -replace '\\', '/'
$wslProbeLines = @(& wsl.exe -d $Distribution -- wslpath -a -u $portableProbeDirectory 2>&1 |
    ForEach-Object { [string]$_ })
if ($LASTEXITCODE -ne 0 -or -not $wslProbeLines) { throw 'Could not resolve the aftertouch proof directory in WSL' }
$wslProbe = ([string]($wslProbeLines | Select-Object -Last 1)).Trim()
$versionLines = @(& wsl.exe -d $Distribution -- drumgizmo --version 2>&1 | ForEach-Object { [string]$_ })
if ($LASTEXITCODE -ne 0) { throw "DrumGizmo is unavailable in WSL distribution $Distribution" }
$version = ($versionLines | Select-Object -First 1).Trim()

$validationLines = @(& wsl.exe -d $Distribution -- dgvalidator --pedantic --verbose $wslDrumkit 2>&1 |
    ForEach-Object { [string]$_ })
$validationExit = $LASTEXITCODE
if ($validationExit -ne 0) {
    throw "dgvalidator rejected the kit: $($validationLines -join '; ')"
}

# Both engines are synthetic. `timeout` bounds a defective engine invocation;
# no ALSA/JACK/MIDI endpoint is requested or opened.
$engineLines = @(& wsl.exe -d $Distribution -- timeout 180s drumgizmo -s `
    -i test -I 'p=0.2,instr=0,len=1' -o dummy -e 48000 $wslDrumkit 2>&1 |
    ForEach-Object { [string]$_ })
$engineExit = $LASTEXITCODE
if ($engineExit -ne 0) {
    $tail = @($engineLines | Select-Object -Last 20) -join '; '
    throw "DrumGizmo dummy-engine load failed with exit code ${engineExit}: $tail"
}
$engineLoaded = $engineLines -contains 'done'
$engineQuitCleanly = $engineLines -contains 'Quit.'
if (-not $engineLoaded -or -not $engineQuitCleanly) {
    $tail = @($engineLines | Select-Object -Last 20) -join '; '
    throw "DrumGizmo did not confirm a complete load and clean shutdown: $tail"
}

foreach ($probeName in @('control', 'choke')) {
    $probeLines = @(& wsl.exe -d $Distribution -- timeout 180s drumgizmo -s `
        -i midifile -I "file=$wslProbe/$probeName.mid,midimap=$wslKit/midimap.xml" `
        -o wavfile -O "file=$wslProbe/$probeName,srate=48000" `
        -p 'close=1,diverse=0,random=0' -e 144000 $wslDrumkit 2>&1 |
        ForEach-Object { [string]$_ })
    if ($LASTEXITCODE -ne 0) {
        $tail = @($probeLines | Select-Object -Last 20) -join '; '
        throw "DrumGizmo aftertouch $probeName render failed: $tail"
    }
}
$aftertouchReport = Join-Path $probeDirectory 'proof.json'
& $python -m drum_sampler.drumgizmo_probe analyze --output-directory $probeDirectory --report $aftertouchReport
if ($LASTEXITCODE -ne 0) { throw 'DrumGizmo aftertouch audio proof failed' }
$aftertouchProof = Get-Content -LiteralPath $aftertouchReport -Raw | ConvertFrom-Json

$reportDocument = [ordered]@{
    format = 'drumgizmo-external-smoke-report/v1'
    status = 'pass'
    kit_directory = $KitDirectory
    drumkit_sha256 = $drumkitSha256
    midimap_sha256 = $midimapSha256
    internal_validation = [ordered]@{
        report = $ValidationReport
        report_sha256 = (Get-FileHash -LiteralPath $ValidationReport -Algorithm SHA256).Hash.ToLowerInvariant()
        status = [string]$validation.status
    }
    distribution = $Distribution
    drumgizmo_version = $version
    validator = [ordered]@{ executable = 'dgvalidator'; pedantic = $true; exit_code = $validationExit }
    engine = [ordered]@{
        executable = 'drumgizmo'
        streaming = $true
        input = 'test'
        output = 'dummy'
        frames = 48000
        exit_code = $engineExit
        loaded = $engineLoaded
        quit_cleanly = $engineQuitCleanly
    }
    aftertouch_choke = $aftertouchProof
    kit = $validation.kit
    hardware_io = 'disabled; synthetic test input and dummy audio output'
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Report) | Out-Null
$reportDocument | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Report -Encoding utf8
Write-Output "DrumGizmo WSL smoke passed: $Report"
