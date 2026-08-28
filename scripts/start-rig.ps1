[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)] [string] $Project,
    [Parameter(Mandatory = $true)] [string] $SessionConfig,
    [Parameter(Mandatory = $true)] [string] $StateFile,
    [string] $Output = '',
    [switch] $ReplaceBuild,
    [switch] $ConfirmStart
)

$ErrorActionPreference = 'Stop'
$scripts = $PSScriptRoot
& (Join-Path $scripts 'build-rig.ps1') -Project $Project -Output $Output -Replace:$ReplaceBuild -Confirm:$false | Write-Output
if (-not $ConfirmStart -and -not $WhatIfPreference) {
    throw 'Build completed. Review its report, then pass -ConfirmStart to launch the configured converter and SD3.'
}
& (Join-Path $scripts 'start-live.ps1') -Config $SessionConfig -StateFile $StateFile -ConfirmStart:$ConfirmStart -WhatIf:$WhatIfPreference
