function Write-LiveJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] [object] $Document
    )

    $fullPath = [IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $fullPath
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $temporary = "$fullPath.tmp.$([guid]::NewGuid().ToString('N'))"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText(
            $temporary,
            (($Document | ConvertTo-Json -Depth 12) + [Environment]::NewLine),
            $encoding
        )
        Move-Item -LiteralPath $temporary -Destination $fullPath -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Get-LiveFileSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)] [string] $Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-LiveJson {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)] [string] $Path)

    $encoding = New-Object System.Text.UTF8Encoding($false)
    $text = [IO.File]::ReadAllText([IO.Path]::GetFullPath($Path), $encoding)
    return ($text | ConvertFrom-Json)
}
