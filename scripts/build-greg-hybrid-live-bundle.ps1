[CmdletBinding()]
param(
    [string] $Project = 'local\rig\greg-hybrid-r15-flash-only-v2.yaml',
    [string] $OutputDirectory = '',
    [string] $ArchivePath = '',
    [switch] $PrivateAssets,
    [string] $Sd3Preset = 'captures\sd3\Greg_Hybrid_r15_MegaKit_v23_approved.sd3p',
    [string] $DrumGizmoKit = 'build\capture\greg-hybrid-r15-full-v23\drumgizmo-kit-current-r5',
    [switch] $Offline,
    [switch] $Replace
)

$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'Bundle construction requires PowerShell 7; the generated installer remains compatible with Windows PowerShell 5.1.'
}
$repoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$hostPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $hostPython -PathType Leaf)) {
    throw 'The reviewed project .venv is required to construct the offline bundle.'
}
$projectPath = [IO.Path]::GetFullPath((Join-Path $repoRoot $Project))
if (-not (Test-Path -LiteralPath $projectPath -PathType Leaf)) { throw "Project not found: $projectPath" }
$projectSha = (Get-FileHash -LiteralPath $projectPath -Algorithm SHA256).Hash.ToLowerInvariant()
$scope = if ($PrivateAssets) { 'private-with-assets' } else { 'tools-only' }
$scopeId = if ($PrivateAssets) { 'private' } else { 'tools' }
$bundleId = "ghl-$($projectSha.Substring(0, 12))-$scopeId"

$releaseRoot = Join-Path $repoRoot 'build\releases'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $releaseRoot $bundleId }
if ([string]::IsNullOrWhiteSpace($ArchivePath)) {
    $ArchivePath = Join-Path $releaseRoot ("greg-hybrid-live-win-x64-$($projectSha.Substring(0, 12))-$scope.zip")
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
$archive = [IO.Path]::GetFullPath($ArchivePath)
$stagingRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'build\deployment-staging'))
$staging = Join-Path $stagingRoot ($bundleId + '.staging.' + [guid]::NewGuid().ToString('N'))

function Assert-UnderBuild([string] $Path) {
    $buildRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'build')) + [IO.Path]::DirectorySeparatorChar
    $candidate = [IO.Path]::GetFullPath($Path)
    if (-not $candidate.StartsWith($buildRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Bundle output must remain under the repository build directory: $candidate"
    }
}
Assert-UnderBuild $output
Assert-UnderBuild $archive
Assert-UnderBuild $staging
if ((Test-Path -LiteralPath $output) -or (Test-Path -LiteralPath $archive)) {
    if (-not $Replace) { throw "Bundle output already exists. Pass -Replace to archive it before rebuilding: $output" }
    $suffix = '.backup.' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
    if (Test-Path -LiteralPath $output) { Move-Item -LiteralPath $output -Destination ($output + $suffix) }
    if (Test-Path -LiteralPath $archive) { Move-Item -LiteralPath $archive -Destination ($archive + $suffix) }
    if (Test-Path -LiteralPath ($archive + '.sha256')) {
        Move-Item -LiteralPath ($archive + '.sha256') -Destination ($archive + '.sha256' + $suffix)
    }
}
New-Item -ItemType Directory -Force -Path $staging, (Split-Path -Parent $output), (Split-Path -Parent $archive) | Out-Null

$excludedDirectories = @('.git', '.venv', 'build', 'local', 'captures', '__pycache__', '.pytest_cache', '.pio')
$excludedExtensions = @('.pyc', '.pyo', '.obj', '.pdb', '.ilk')
function Copy-CleanTree([string] $RelativePath) {
    $source = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) { throw "Bundle source is missing: $source" }
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        $destination = Join-Path $staging $RelativePath
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
        return
    }
    foreach ($file in Get-ChildItem -LiteralPath $source -Recurse -File -Force) {
        $relativeInside = [IO.Path]::GetRelativePath($source, $file.FullName)
        $parts = $relativeInside -split '[\\/]'
        if (@($parts | Where-Object { $excludedDirectories -contains $_ }).Count) { continue }
        if ($excludedExtensions -contains $file.Extension.ToLowerInvariant()) { continue }
        $destination = Join-Path (Join-Path $staging $RelativePath) $relativeInside
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
}

try {
    foreach ($path in @(
        'apps\control-center', 'apps\ddti', 'apps\ddrum4-bank-builder', 'apps\drum-sampler',
        'packages\drum-domain', 'tools\midi-lab', 'tools\rig-compiler', 'contracts', 'profiles',
        'firmware\ddrum4-midi-bridge', 'scripts', 'docs', 'deployment\windows-live',
        'drum_toolchain.py', 'pyproject.toml', 'README.md', 'architecture_finale_edrum_ddrum4_sd3.md',
        'Launch-Greg-Hybrid-Live.cmd', 'Stop-Greg-Hybrid-Live.cmd'
    )) { Copy-CleanTree $path }

    foreach ($name in @('Install-Live-Rig.ps1', 'Install-Live-Rig.cmd', 'Test-Live-Rig.ps1',
                         'Test-Live-Rig.cmd', 'Configure-Live-Rig.ps1', 'Configure-Live-Rig.cmd',
                         'README-FIRST.fr.md')) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "deployment\windows-live\$name") -Destination (Join-Path $staging $name)
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $staging 'deployment') | Out-Null
    Copy-Item -LiteralPath $projectPath -Destination (Join-Path $staging 'deployment\live-project.yaml')

    $converterSource = Join-Path $repoRoot 'build\modernizer-desktop-msvc\ddrum4_converter_artefacts\Release'
    if (-not (Test-Path -LiteralPath (Join-Path $converterSource 'ddrum4 Converter.exe'))) {
        throw 'Build the reviewed Release converter before packaging.'
    }
    $converterTarget = Join-Path $staging 'build\modernizer-desktop-msvc\ddrum4_converter_artefacts\Release'
    New-Item -ItemType Directory -Force -Path $converterTarget | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $converterSource -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $converterTarget -Recurse -Force
    }

    $compiledTarget = Join-Path $staging 'build\rig\current'
    & $hostPython -m rig_compiler.cli compile $projectPath --output $compiledTarget
    if ($LASTEXITCODE -ne 0) { throw 'Rig compilation failed while constructing the bundle.' }

    $privateAssetFacts = [System.Collections.Generic.List[object]]::new()
    if ($PrivateAssets) {
        $sd3Path = [IO.Path]::GetFullPath((Join-Path $repoRoot $Sd3Preset))
        $drumgizmoPath = [IO.Path]::GetFullPath((Join-Path $repoRoot $DrumGizmoKit))
        if (-not (Test-Path -LiteralPath $sd3Path -PathType Leaf)) { throw "Approved SD3 preset not found: $sd3Path" }
        if (-not (Test-Path -LiteralPath (Join-Path $drumgizmoPath 'drumkit.xml') -PathType Leaf)) {
            throw "Validated DrumGizmo kit not found: $drumgizmoPath"
        }
        New-Item -ItemType Directory -Force -Path (Join-Path $staging 'assets\sd3'), (Join-Path $staging 'assets\drumgizmo') | Out-Null
        Copy-Item -LiteralPath $sd3Path -Destination (Join-Path $staging 'assets\sd3\Greg_Hybrid_r15_MegaKit_v23_approved.sd3p')
        Copy-Item -LiteralPath $drumgizmoPath -Destination (Join-Path $staging 'assets\drumgizmo\Greg-Hybrid-r15-v23-r5') -Recurse
        $privateAssetFacts.Add([ordered]@{ kind = 'sd3-user-preset'; path = 'assets/sd3/Greg_Hybrid_r15_MegaKit_v23_approved.sd3p'; redistribution = 'prohibited' })
        $privateAssetFacts.Add([ordered]@{ kind = 'drumgizmo-derived-kit'; path = 'assets/drumgizmo/Greg-Hybrid-r15-v23-r5'; redistribution = 'prohibited' })
    } else {
        & (Join-Path $repoRoot 'scripts\assert-tools-only-payload.ps1') -Root $staging
        if ($LASTEXITCODE -ne 0) { throw 'The tools-only payload policy rejected the staged bundle.' }
    }

    $pythonVersion = '3.12.10'
    $pythonUri = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-amd64.zip"
    $pythonSha = '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
    $cache = Join-Path $repoRoot 'build\deployment-cache'
    $pythonArchive = Join-Path $cache "python-$pythonVersion-embed-amd64.zip"
    $wheelhouse = Join-Path $cache 'wheels-cp312-win-amd64'
    New-Item -ItemType Directory -Force -Path $cache, $wheelhouse | Out-Null
    if (-not (Test-Path -LiteralPath $pythonArchive)) {
        if ($Offline) { throw "Offline Python runtime cache is missing: $pythonArchive" }
        Invoke-WebRequest -Uri $pythonUri -OutFile $pythonArchive -UseBasicParsing
    }
    $actualPythonSha = (Get-FileHash -LiteralPath $pythonArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualPythonSha -ne $pythonSha) { throw "Embedded Python archive checksum mismatch: $actualPythonSha" }
    $runtime = Join-Path $staging '.venv\Scripts'
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $runtime

    $requirements = Join-Path $repoRoot 'deployment\windows-live\requirements.lock.txt'
    if (-not $Offline) {
        & $hostPython -m pip download --disable-pip-version-check --require-hashes --only-binary=:all: --destination-directory $wheelhouse --requirement $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Could not populate the offline wheelhouse.' }
    }
    $sitePackages = Join-Path $runtime 'Lib\site-packages'
    New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
    & $hostPython -m pip install --disable-pip-version-check --require-hashes --no-index --find-links $wheelhouse --target $sitePackages --requirement $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the locked dependencies into the embedded runtime.' }

    $pth = @(
        'python312.zip', '.', 'Lib\site-packages',
        '..\..\apps\control-center\src', '..\..\apps\ddti\src',
        '..\..\apps\ddrum4-bank-builder\src', '..\..\apps\drum-sampler\src',
        '..\..\packages\drum-domain\src', '..\..\tools\midi-lab\src',
        '..\..\tools\rig-compiler\src', '..\..', 'import site', ''
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $runtime 'python312._pth'), $pth, (New-Object Text.UTF8Encoding($false)))

    $portableControlCenter = @'
@echo off
setlocal
cd /d "%~dp0"
set "DRUM_CONTROL_CENTER_PROJECT=%~dp0deployment\live-project.yaml"
set "DRUM_CONTROL_CENTER_OUTPUT=%~dp0build\rig\current"
start "Drum Control Center" "%~dp0.venv\Scripts\pythonw.exe" -m control_center.gui
endlocal
'@
    [IO.File]::WriteAllText((Join-Path $staging 'Launch-Control-Center.cmd'), $portableControlCenter, [Text.Encoding]::ASCII)

    $previousBytecodeSetting = [Environment]::GetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', 'Process')
    try {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', '1', 'Process')
        & (Join-Path $runtime 'python.exe') -c "import yaml,mido,rtmidi,numpy,scipy,sounddevice,soundcard,jsonschema,PySide6; import control_center,ddti,ddrum4_bank,drum_sampler,drum_domain,midi_lab,rig_compiler"
        if ($LASTEXITCODE -ne 0) { throw 'The embedded runtime failed its import smoke test.' }
    } finally {
        [Environment]::SetEnvironmentVariable('PYTHONDONTWRITEBYTECODE', $previousBytecodeSetting, 'Process')
    }

    $report = Get-Content -LiteralPath (Join-Path $compiledTarget 'project-report.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $gitCommit = (& git -C $repoRoot rev-parse HEAD 2>$null | Out-String).Trim()
    $gitDirty = [bool]((& git -C $repoRoot status --porcelain 2>$null | Out-String).Trim())
    $fileRecords = [System.Collections.Generic.List[object]]::new()
    foreach ($file in Get-ChildItem -LiteralPath $staging -Recurse -File -Force | Sort-Object FullName) {
        if ($file.Name -eq 'bundle-manifest.json') { continue }
        $relative = [IO.Path]::GetRelativePath($staging, $file.FullName).Replace('\', '/')
        $fileRecords.Add([ordered]@{
            path = $relative
            size = $file.Length
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        })
    }
    $manifest = [ordered]@{
        kind = 'greg-hybrid-live-bundle/v1'
        bundle_id = $bundleId
        scope = $scope
        platform = 'windows-11-x64'
        created_utc = [DateTime]::UtcNow.ToString('o')
        source = @{ git_commit = $gitCommit; dirty = $gitDirty; project_sha256 = $projectSha }
        embedded_python = @{ version = $pythonVersion; source = $pythonUri; sha256 = $pythonSha }
        project = @{ deployment = $report.deployment; validation_stage = $report.validation_stage; source_sha256 = $report.source_sha256 }
        converter = 'build/modernizer-desktop-msvc/ddrum4_converter_artefacts/Release/ddrum4 Converter.exe'
        private_assets = @($privateAssetFacts)
        prerequisites = @('Windows 11 x64', 'UMC404HD driver', 'Superior Drummer 3 plus licensed EZX libraries', 'configured MIDI ports', 'optional DrumGizmo host')
        safety = 'Live launch remains fail-closed until the compiled project is hardware-verified and local paths/ports are configured.'
        files = @($fileRecords)
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $staging 'bundle-manifest.json') -Encoding utf8NoBOM

    & (Join-Path $staging 'Test-Live-Rig.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Staged bundle diagnostic failed.' }
    Move-Item -LiteralPath $staging -Destination $output

    $tar = (Get-Command tar.exe -ErrorAction Stop).Source
    & $tar -a -c -f $archive -C (Split-Path -Parent $output) (Split-Path -Leaf $output)
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the deployment ZIP archive.' }
    $archiveSha = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$archiveSha  $([IO.Path]::GetFileName($archive))" | Set-Content -LiteralPath ($archive + '.sha256') -Encoding ascii
    Write-Output "Bundle directory: $output"
    Write-Output "Archive: $archive"
    Write-Output "Archive SHA-256: $archiveSha"
    Write-Output "Scope: $scope; validation_stage=$($report.validation_stage)"
} catch {
    if (Test-Path -LiteralPath $staging) {
        Write-Warning "Failed staging directory retained for diagnosis: $staging"
    }
    throw
}
