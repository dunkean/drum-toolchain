[CmdletBinding()]
param(
    [string] $DestinationRoot = (Join-Path $env:LOCALAPPDATA 'GregHybridLive'),
    [switch] $NoDesktopShortcuts,
    [switch] $Configure
)

$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifestPath = Join-Path $bundleRoot 'bundle-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Bundle manifest not found: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$manifest.kind -ne 'greg-hybrid-live-bundle/v1') {
    throw "Unsupported bundle manifest kind: $($manifest.kind)"
}

Write-Output "Verifying $(@($manifest.files).Count) bundle files before installation..."
$declaredPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in @($manifest.files)) {
    $relative = [string]$entry.path
    if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
        throw "Unsafe manifest path: $relative"
    }
    if (-not $declaredPaths.Add($relative.Replace('\', '/'))) { throw "Duplicate manifest path: $relative" }
    $path = Join-Path $bundleRoot $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Bundle file is missing: $relative" }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$entry.sha256).ToLowerInvariant()) {
        throw "Bundle checksum mismatch: $relative"
    }
}
$rootPrefixLength = $bundleRoot.TrimEnd('\', '/').Length + 1
foreach ($file in Get-ChildItem -LiteralPath $bundleRoot -Recurse -File -Force) {
    if ($file.FullName -eq $manifestPath) { continue }
    $relative = $file.FullName.Substring($rootPrefixLength).Replace('\', '/')
    if (-not $declaredPaths.Contains($relative)) {
        throw "Undeclared file found beside verified payload: $relative"
    }
}

$destination = [IO.Path]::GetFullPath($DestinationRoot)
$versions = Join-Path $destination 'versions'
$versionDirectory = Join-Path $versions ([string]$manifest.bundle_id)
$longestInstalledPath = @($manifest.files | ForEach-Object {
    (Join-Path $versionDirectory ([string]$_.path)).Length
} | Measure-Object -Maximum).Maximum
if ($longestInstalledPath -gt 240) {
    throw "Installation path is too deep for bundled native audio/Qt libraries (maximum projected path: $longestInstalledPath characters). Choose a shorter -DestinationRoot, for example C:\GregHybridLive."
}
New-Item -ItemType Directory -Force -Path $versions | Out-Null
if (-not (Test-Path -LiteralPath $versionDirectory)) {
    $staging = Join-Path $versions ('.installing-' + $manifest.bundle_id + '-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        foreach ($item in Get-ChildItem -LiteralPath $bundleRoot -Force) {
            Copy-Item -LiteralPath $item.FullName -Destination $staging -Recurse -Force
        }
        Move-Item -LiteralPath $staging -Destination $versionDirectory
    } finally {
        if (Test-Path -LiteralPath $staging) {
            throw "Incomplete staging directory retained for diagnosis: $staging"
        }
    }
} else {
    Write-Output "This exact bundle version is already installed: $versionDirectory"
}

# Validate the copied version before changing the active pointer or desktop
# shortcuts. A failed update therefore leaves the previous installation active.
& (Join-Path $versionDirectory 'Test-Live-Rig.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Installed bundle diagnostic failed; the previous active version was preserved.' }

$current = [ordered]@{
    kind = 'greg-hybrid-live-current-install/v1'
    bundle_id = [string]$manifest.bundle_id
    path = $versionDirectory
    installed_utc = [DateTime]::UtcNow.ToString('o')
}
$currentPath = Join-Path $destination 'current.json'
$temporary = "$currentPath.tmp.$([guid]::NewGuid().ToString('N'))"
[IO.File]::WriteAllText(
    $temporary,
    (($current | ConvertTo-Json -Depth 4) + [Environment]::NewLine),
    (New-Object Text.UTF8Encoding($false))
)
Move-Item -LiteralPath $temporary -Destination $currentPath -Force

if (-not $NoDesktopShortcuts) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcut in @(
        @{ Name = 'Greg Hybrid - Control Center.lnk'; Target = 'Launch-Control-Center.cmd'; Description = 'Edit, simulate and validate the Greg Hybrid drum rig' },
        @{ Name = 'Greg Hybrid - Live.lnk'; Target = 'Launch-Greg-Hybrid-Live.cmd'; Description = 'Fail-closed one-click live launch' },
        @{ Name = 'Greg Hybrid - Stop Live.lnk'; Target = 'Stop-Greg-Hybrid-Live.cmd'; Description = 'Stop only processes owned by the live launcher and restore power settings' }
    )) {
        $link = $shell.CreateShortcut((Join-Path $desktop $shortcut.Name))
        $link.TargetPath = Join-Path $versionDirectory $shortcut.Target
        $link.WorkingDirectory = $versionDirectory
        $link.Description = $shortcut.Description
        $link.Save()
    }
}
if ($Configure) {
    & (Join-Path $versionDirectory 'Configure-Live-Rig.ps1')
}
Write-Output "Greg Hybrid Live installed: $versionDirectory"
Write-Output "Current installation pointer: $currentPath"
