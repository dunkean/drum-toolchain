[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Report-Command([string]$Name) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        Write-Output ("{0}: {1}" -f $Name, $command.Source)
        return $true
    }
    Write-Warning ("{0}: not found on PATH" -f $Name)
    return $false
}

Write-Output 'Drum Toolchain environment'
Report-Command git | Out-Null
Report-Command python | Out-Null
Report-Command cmake | Out-Null
Report-Command ninja | Out-Null
$hasPio = Report-Command pio

if (-not $hasPio) {
    $fallback = 'C:\Users\grego\AppData\Roaming\Python\Python313\Scripts\pio.exe'
    if (Test-Path -LiteralPath $fallback) {
        Write-Output ("pio fallback: {0}" -f $fallback)
    }
}

$ddrumRoot = if ($env:DDRUM4UI_ROOT) { $env:DDRUM4UI_ROOT } else { 'D:\Studio\ddrum4ui' }
foreach ($name in @('ddrum4ui.exe', 'ddrum4edit.exe')) {
    $path = Join-Path $ddrumRoot $name
    if (Test-Path -LiteralPath $path) {
        Write-Output ("{0}: {1}" -f $name, $path)
    } else {
        Write-Warning ("{0}: not found under {1}" -f $name, $ddrumRoot)
    }
}
