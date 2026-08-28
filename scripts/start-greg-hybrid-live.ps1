[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string] $Config = '',
    [string] $StateFile = '',
    [switch] $ConfirmStart
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Config)) { $Config = Join-Path $repoRoot 'local\greg-hybrid-live-session.local.json' }
if ([string]::IsNullOrWhiteSpace($StateFile)) { $StateFile = Join-Path $repoRoot 'local\greg-hybrid-live-state.local.json' }
if (-not $ConfirmStart -and -not $WhatIfPreference) {
    throw 'One-click live launch is explicit; pass -ConfirmStart or use Launch-Greg-Hybrid-Live.cmd.'
}

try {
    & (Join-Path $PSScriptRoot 'start-live.ps1') -Config $Config -StateFile $StateFile -ConfirmStart:$ConfirmStart -WhatIf:$WhatIfPreference -Confirm:$false
    if (-not $WhatIfPreference) {
        & (Join-Path $PSScriptRoot 'set-low-latency.ps1') -Config $Config -StateFile $StateFile -ConfirmApply -Confirm:$false
    }
} catch {
    if (-not $WhatIfPreference -and (Test-Path -LiteralPath $StateFile)) {
        & (Join-Path $PSScriptRoot 'restore-live.ps1') -StateFile $StateFile -Confirm:$false
    }
    throw
}
Write-Output 'Greg Hybrid live session is running: Converter auto-started, SD3 launched, and the owned power plan applied.'
