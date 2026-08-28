[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [string]$Browser,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if ([IO.Path]::GetExtension($sourcePath) -ne ".md") {
    throw "Source must be a Markdown file: $sourcePath"
}
$outputPath = [IO.Path]::GetFullPath($Output, (Get-Location).Path)
$outputParent = Split-Path -Parent $outputPath
if (-not (Test-Path -LiteralPath $outputParent -PathType Container)) {
    throw "Output directory does not exist: $outputParent"
}
if ((Test-Path -LiteralPath $outputPath) -and -not $Force) {
    throw "Output already exists; pass -Force to replace it: $outputPath"
}

if (-not $Browser) {
    $candidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
    $Browser = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $Browser -or -not (Test-Path -LiteralPath $Browser -PathType Leaf)) {
    throw "A Chromium-compatible browser executable is required. Pass -Browser explicitly."
}

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporaryDirectory = Join-Path $temporaryRoot ("drum-toolchain-pdf-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
try {
    $htmlBody = (ConvertFrom-Markdown -Path $sourcePath).Html
    $htmlPath = Join-Path $temporaryDirectory "document.html"
    $style = @"
<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><style>
@page { size: A4 landscape; margin: 12mm; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #17202a; font-size: 9pt; line-height: 1.35; }
h1 { font-size: 22pt; margin: 0 0 8mm; color: #111827; }
h2 { font-size: 14pt; margin: 7mm 0 3mm; break-after: avoid; color: #1f2937; }
h3 { font-size: 11pt; break-after: avoid; }
code { font-family: "Cascadia Mono", Consolas, monospace; background: #eef2f7; padding: 0 2px; }
table { width: 100%; border-collapse: collapse; table-layout: auto; margin: 3mm 0 6mm; font-size: 7.4pt; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #1f2937; color: white; text-align: left; }
th, td { border: 1px solid #cbd5e1; padding: 3px 5px; vertical-align: top; overflow-wrap: anywhere; }
tbody tr:nth-child(even) { background: #f8fafc; }
ul, ol { margin-top: 2mm; }
</style></head><body>
$htmlBody
</body></html>
"@
    [IO.File]::WriteAllText($htmlPath, $style, [Text.UTF8Encoding]::new($false))
    $htmlUri = [uri]$htmlPath
    $arguments = @(
        "--headless",
        "--disable-gpu",
        "--user-data-dir=$(Join-Path $temporaryDirectory 'browser-profile')",
        "--no-pdf-header-footer",
        "--print-to-pdf=$outputPath",
        $htmlUri.AbsoluteUri
    )
    $process = Start-Process -FilePath $Browser -ArgumentList $arguments -PassThru -Wait -WindowStyle Hidden
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
        throw "PDF renderer failed with exit code $($process.ExitCode)"
    }
    Get-Item -LiteralPath $outputPath
}
finally {
    $resolvedTemporary = [IO.Path]::GetFullPath($temporaryDirectory)
    if ($resolvedTemporary.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}
