[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'live-common.ps1')

$temporary = Join-Path ([IO.Path]::GetTempPath()) ("drum-toolchain-live-common-" + [guid]::NewGuid().ToString('N') + '.json')
try {
    Write-LiveJson -Path $temporary -Document ([ordered]@{
        kind = 'live-common-compatibility-smoke'
        schema_version = 1
        value = 'é-drum'
    })
    $document = Read-LiveJson -Path $temporary
    if ($document.kind -ne 'live-common-compatibility-smoke' -or $document.value -ne 'é-drum') {
        throw 'The live JSON helper did not round-trip Unicode JSON.'
    }
    $bytes = [IO.File]::ReadAllBytes($temporary)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        throw 'The live JSON helper emitted a UTF-8 BOM.'
    }
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
}
Write-Output 'live JSON compatibility smoke passed'
