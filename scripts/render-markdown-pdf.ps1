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
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporary = Join-Path $temporaryRoot ('drum-toolchain-pdf-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    $htmlPath = Join-Path $temporary 'document.html'
    $renderPath = Join-Path $temporary 'rendered.pdf'
    Set-Content -LiteralPath $htmlPath -Value $html -Encoding utf8NoBOM
    $parent = Split-Path -Parent $outputPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $uri = [Uri]::new($htmlPath).AbsoluteUri
    $browserProfile = Join-Path $temporary 'browser-profile'
    $process = Start-Process -FilePath $browser -ArgumentList @('--headless=new', '--disable-gpu', '--no-pdf-header-footer', "--user-data-dir=$browserProfile", "--print-to-pdf=$renderPath", $uri) -PassThru -WindowStyle Hidden
    $process.WaitForExit()
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path -LiteralPath $renderPath -PathType Leaf); $attempt++) {
        Start-Sleep -Milliseconds 100
    }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $renderPath -PathType Leaf)) {
        throw "PDF renderer failed with exit code $($process.ExitCode)."
    }
    # Chromium may delegate the final flush to a child process and let the
    # process returned by Start-Process exit first.  Do not return a PDF which
    # is still changing underneath a following git add or file copy.
    $previousHash = ''
    $stablePasses = 0
    for ($attempt = 0; $attempt -lt 100 -and $stablePasses -lt 5; $attempt++) {
        try {
            $pdfBytes = [IO.File]::ReadAllBytes($renderPath)
            $tailStart = [Math]::Max(0, $pdfBytes.Length - 32)
            $tail = [Text.Encoding]::ASCII.GetString($pdfBytes, $tailStart, $pdfBytes.Length - $tailStart)
            $hash = (Get-FileHash -LiteralPath $renderPath -Algorithm SHA256).Hash
            if ($pdfBytes.Length -gt 8 -and $tail.Contains('%%EOF') -and $hash -eq $previousHash) {
                $stablePasses++
            } else {
                $stablePasses = 0
            }
            $previousHash = $hash
        } catch {
            $stablePasses = 0
        }
        if ($stablePasses -lt 5) { Start-Sleep -Milliseconds 100 }
    }
    if ($stablePasses -lt 5) { throw 'PDF renderer did not produce a stable, complete file.' }
    $copied = $false
    for ($attempt = 0; $attempt -lt 100 -and -not $copied; $attempt++) {
        try {
            Copy-Item -LiteralPath $renderPath -Destination $outputPath -Force -ErrorAction Stop
            $copied = $true
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $copied) { throw "Rendered PDF is complete, but destination remains locked: $outputPath" }
} finally {
    $resolvedTemporary = [IO.Path]::GetFullPath($temporary)
    if (-not $resolvedTemporary.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean an unexpected temporary path: $resolvedTemporary"
    }
    for ($attempt = 0; $attempt -lt 20 -and (Test-Path -LiteralPath $resolvedTemporary); $attempt++) {
        try { Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force -ErrorAction Stop } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (Test-Path -LiteralPath $resolvedTemporary) { Write-Warning "Temporary browser profile remains locked: $resolvedTemporary" }
}
Write-Output "Rendered PDF: $outputPath"
