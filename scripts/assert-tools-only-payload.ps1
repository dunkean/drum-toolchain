[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $Root
)

$ErrorActionPreference = 'Stop'
$payloadRoot = [IO.Path]::GetFullPath($Root)
if (-not (Test-Path -LiteralPath $payloadRoot -PathType Container)) {
    throw "Tools-only payload root not found: $payloadRoot"
}
if (Test-Path -LiteralPath (Join-Path $payloadRoot 'assets')) {
    throw 'A tools-only bundle must not contain an assets directory.'
}

$restrictedExtensions = @(
    '.sd3p', '.wav', '.wave', '.flac', '.aif', '.aiff', '.ogg', '.mp3',
    '.edp', '.syx', '.dsnd', '.dkit', '.dgkit'
)
$restricted = @(
    Get-ChildItem -LiteralPath $payloadRoot -Recurse -File -Force | Where-Object {
        $extension = $_.Extension.ToLowerInvariant()
        ($restrictedExtensions -contains $extension) -or
        ($extension -eq '.zip' -and $_.Name -match '(?i)(drumgizmo|mega.?kit|sound.?bank|sample.?pack)')
    }
)
if ($restricted.Count) {
    $preview = @($restricted | Select-Object -First 10 | ForEach-Object {
        $_.FullName.Substring($payloadRoot.TrimEnd('\', '/').Length + 1)
    }) -join ', '
    throw "Private/audio material is forbidden in a tools-only bundle: $preview"
}

Write-Output "tools-only payload policy passed: $payloadRoot"
