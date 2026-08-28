[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)] [string] $InputMarkdown,
    [Parameter(Mandatory = $true)] [string] $OutputPdf
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
$markdownPath = (Resolve-Path -LiteralPath $InputMarkdown).Path
$outputPath = [IO.Path]::GetFullPath($OutputPdf)
$edgeCandidates = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Google\Chrome\Application\chrome.exe'
)
$browser = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $browser) { throw 'Edge or Chrome is required for deterministic headless PDF rendering.' }
if (-not $PSCmdlet.ShouldProcess($outputPath, "Render $markdownPath as PDF")) { return }

$body = & $python -c "import markdown,sys; sys.stdout.reconfigure(encoding='utf-8'); print(markdown.markdown(open(sys.argv[1],encoding='utf-8').read(),extensions=['tables','fenced_code']))" $markdownPath
if ($LASTEXITCODE -ne 0) { throw 'Markdown conversion failed.' }
$style = @'
body { font: 10pt "Segoe UI", sans-serif; color: #20242b; margin: 18mm; line-height: 1.35; }
h1, h2 { color: #7b1e24; break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 7.5pt; margin: 10px 0 18px; }
th { background: #252b33; color: white; }
th, td { border: 1px solid #aeb4bc; padding: 4px 5px; vertical-align: top; }
tr:nth-child(even) { background: #f2f4f6; }
code { font-family: Consolas, monospace; font-size: 0.92em; }
@page { size: A4 landscape; margin: 10mm; }
'@
$html = "<!doctype html><html><head><meta charset='utf-8'><style>$style</style></head><body>$body</body></html>"
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('drum-toolchain-pdf-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $htmlPath = Join-Path $temporary 'document.html'
    Set-Content -LiteralPath $htmlPath -Value $html -Encoding utf8NoBOM
    $parent = Split-Path -Parent $outputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $uri = [Uri]::new($htmlPath).AbsoluteUri
    $browserProfile = Join-Path $temporary 'browser-profile'
    $process = Start-Process -FilePath $browser -ArgumentList @('--headless=new', '--disable-gpu', '--no-pdf-header-footer', "--user-data-dir=$browserProfile", "--print-to-pdf=$outputPath", $uri) -PassThru -WindowStyle Hidden
    $process.WaitForExit()
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
        throw "PDF renderer failed with exit code $($process.ExitCode)."
    }
} finally {
    for ($attempt = 0; $attempt -lt 20 -and (Test-Path -LiteralPath $temporary); $attempt++) {
        try { Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction Stop } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (Test-Path -LiteralPath $temporary) { Write-Warning "Temporary browser profile remains locked: $temporary" }
}
Write-Output "Rendered PDF: $outputPath"
