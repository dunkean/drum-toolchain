[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$markdown = Join-Path $repoRoot '.venv\Scripts\markdown_py.exe'
$edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$InputPath = [IO.Path]::GetFullPath($InputPath)
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) {
    throw "Markdown input is missing: $InputPath"
}
if (-not (Test-Path -LiteralPath $markdown -PathType Leaf)) {
    throw "Python-Markdown CLI is missing: $markdown"
}
if (-not (Test-Path -LiteralPath $edge -PathType Leaf)) {
    throw "Microsoft Edge is missing: $edge"
}

$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporary = Join-Path $temporaryRoot ("drum-toolchain-pdf-" + [guid]::NewGuid().ToString('N'))
if (-not ([IO.Path]::GetFullPath($temporary).StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase))) {
    throw 'Refusing to create a PDF workspace outside the system temporary directory'
}
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $fragment = Join-Path $temporary 'document.fragment.html'
    $html = Join-Path $temporary 'document.html'
    $profile = Join-Path $temporary 'edge-profile'
    & $markdown -x tables -x fenced_code -f $fragment $InputPath
    if ($LASTEXITCODE -ne 0) { throw "Markdown rendering failed with exit code $LASTEXITCODE" }
    $body = Get-Content -LiteralPath $fragment -Raw
    $title = [Net.WebUtility]::HtmlEncode([IO.Path]::GetFileNameWithoutExtension($InputPath))
    $document = @"
<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>$title</title>
<style>
@page { size: A4; margin: 14mm 13mm 16mm; }
* { box-sizing: border-box; }
body { color: #18212b; font: 10.2pt/1.42 "Segoe UI", Arial, sans-serif; margin: 0; }
h1 { color: #7e1f27; font-size: 23pt; line-height: 1.12; margin: 0 0 12pt; }
h2 { color: #9b2d35; font-size: 16pt; margin: 18pt 0 7pt; break-after: avoid; }
h3 { color: #333f4c; font-size: 12.5pt; margin: 13pt 0 5pt; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; font-size: 8.4pt; break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #2c3743; color: white; text-align: left; }
th, td { border: 0.5pt solid #aeb7c0; padding: 4pt 5pt; vertical-align: top; }
tbody tr:nth-child(even) { background: #f3f5f7; }
code { background: #eef1f4; border-radius: 2pt; padding: 1pt 2pt; font-family: Consolas, monospace; font-size: 8.8pt; }
pre { background: #202832; color: #f5f7f9; padding: 8pt; border-radius: 4pt; white-space: pre-wrap; break-inside: avoid; }
pre code { background: transparent; color: inherit; padding: 0; }
blockquote { border-left: 3pt solid #9b2d35; color: #46515c; margin-left: 0; padding-left: 10pt; }
a { color: #7e1f27; text-decoration: none; }
</style></head><body>$body</body></html>
"@
    Set-Content -LiteralPath $html -Value $document -Encoding utf8NoBOM
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
    $uri = [Uri]::new($html).AbsoluteUri
    $arguments = @(
        '--headless', '--disable-gpu', '--disable-background-mode', '--no-first-run',
        '--no-pdf-header-footer',
        "--user-data-dir=$profile", "--print-to-pdf=$OutputPath", $uri
    )
    $process = Start-Process -FilePath $edge -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
        throw "Edge PDF rendering failed with exit code $($process.ExitCode)"
    }
    Write-Output "Rendered PDF: $OutputPath"
} finally {
    $resolvedTemporary = [IO.Path]::GetFullPath($temporary)
    if ((Test-Path -LiteralPath $resolvedTemporary) -and
            $resolvedTemporary.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
}
