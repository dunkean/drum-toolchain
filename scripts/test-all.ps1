[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$RefreshEnvironment
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
$dependencyStamp = Join-Path $venvRoot '.drum-toolchain-dependencies.sha256'
$createdEnvironment = $false

# The verification suite owns its dependencies.  Do not rely on whichever
# interpreter happens to be active (or install packages into it).
if (-not (Test-Path $venvPython)) {
    Write-Output "Creating project-local Python environment at $venvRoot"
    & $Python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "Could not create the project-local virtual environment with $Python" }
    $createdEnvironment = $true
}

$pythonVersion = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.12') {
    throw "scripts/test-all.ps1 requires Python 3.12; the project-local environment uses $pythonVersion. Remove .venv and rerun with -Python <a Python 3.12 executable>."
}

$dependencyFiles = @(
    (Join-Path $repoRoot 'pyproject.toml'),
    (Join-Path $repoRoot 'packages\drum-domain\pyproject.toml'),
    (Join-Path $repoRoot 'apps\ddti\pyproject.toml'),
    (Join-Path $repoRoot 'apps\control-center\pyproject.toml'),
    (Join-Path $repoRoot 'apps\drum-sampler\pyproject.toml'),
    (Join-Path $repoRoot 'apps\ddrum4-bank-builder\pyproject.toml'),
    (Join-Path $repoRoot 'tools\midi-lab\pyproject.toml'),
    (Join-Path $repoRoot 'tools\rig-compiler\pyproject.toml')
)
$dependencyHashInput = ($dependencyFiles | ForEach-Object { (Get-FileHash -Algorithm SHA256 -LiteralPath $_).Hash }) -join "`n"
$dependencyHashBytes = [Text.Encoding]::UTF8.GetBytes($dependencyHashInput)
$sha256 = [Security.Cryptography.SHA256]::Create()
try { $dependencyDigest = $sha256.ComputeHash($dependencyHashBytes) } finally { $sha256.Dispose() }
$dependencyHash = ([BitConverter]::ToString($dependencyDigest) -replace '-', '').ToLowerInvariant()
$installedHash = if (Test-Path -LiteralPath $dependencyStamp) { (Get-Content -LiteralPath $dependencyStamp -Raw).Trim() } else { '' }
$installDependencies = $createdEnvironment -or $RefreshEnvironment -or $installedHash -ne $dependencyHash
if ($installDependencies) {
    Write-Output 'Installing changed Python test dependencies into the project-local environment.'
    & $venvPython -m pip install --disable-pip-version-check -e $repoRoot
    if ($LASTEXITCODE -ne 0) { throw "Workspace dependency installation failed with exit code $LASTEXITCODE" }
    & $venvPython -m pip install --disable-pip-version-check -e "$repoRoot\packages\drum-domain"
    if ($LASTEXITCODE -ne 0) { throw "Drum domain installation failed with exit code $LASTEXITCODE" }
    & $venvPython -m pip install --disable-pip-version-check -e "$repoRoot\apps\ddti[api,gui]"
    if ($LASTEXITCODE -ne 0) { throw "DDTi dependency installation failed with exit code $LASTEXITCODE" }
    & $venvPython -m pip install --disable-pip-version-check -e "$repoRoot\apps\control-center"
    if ($LASTEXITCODE -ne 0) { throw "Control Center dependency installation failed with exit code $LASTEXITCODE" }
    & $venvPython -m pip install --disable-pip-version-check -e "$repoRoot\apps\drum-sampler" -e "$repoRoot\apps\ddrum4-bank-builder" -e "$repoRoot\tools\midi-lab" -e "$repoRoot\tools\rig-compiler"
    if ($LASTEXITCODE -ne 0) { throw "Portable tool installation failed with exit code $LASTEXITCODE" }
    Set-Content -LiteralPath $dependencyStamp -Value $dependencyHash -Encoding ascii -NoNewline
} else {
    Write-Output 'Python dependency manifests are unchanged; reusing the project-local environment.'
}

if (-not (Test-Path (Join-Path $repoRoot 'docs/repository-migration.md'))) {
    throw 'Repository migration log is missing.'
}

Write-Output 'Parsing PowerShell live/ops scripts before any test command runs.'
foreach ($scriptPath in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File) {
    $tokens = $null
    $parseErrors = $null
    [void] [System.Management.Automation.Language.Parser]::ParseFile($scriptPath.FullName, [ref] $tokens, [ref] $parseErrors)
    if ($parseErrors.Count) {
        $details = ($parseErrors | ForEach-Object { "$($_.Extent.StartLineNumber): $($_.Message)" }) -join '; '
        throw "PowerShell syntax error in $($scriptPath.Name): $details"
    }
}
$windowsLiveProfile = Get-Content -LiteralPath (Join-Path $repoRoot 'profiles\live-session.example.json') -Raw | ConvertFrom-Json
if ([string]$windowsLiveProfile.renderer -ne 'sd3') {
    throw 'profiles/live-session.example.json must declare renderer: sd3 for the Windows live scripts.'
}
& (Join-Path $PSScriptRoot 'test-live-scripts.ps1')

Write-Output 'Running shared Python domain, sampler, bank-builder, and MIDI-lab tests.'
Push-Location $repoRoot
try {
    Write-Output 'Running the required offline DDTi safety suite (tests/python/test_ddti.py).'
    & $venvPython -m unittest discover -s tests\python -p test_ddti.py -v
    if ($LASTEXITCODE -ne 0) { throw "DDTi Python tests failed with exit code $LASTEXITCODE" }

    & $venvPython -m unittest discover -s tests\python -v
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }

    & $venvPython -m unittest discover -s apps\control-center\tests -v
    if ($LASTEXITCODE -ne 0) { throw "Control Center tests failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

& (Join-Path $PSScriptRoot 'test-firmware-core.ps1')
& (Join-Path $PSScriptRoot 'test-modernizer-core.ps1')
