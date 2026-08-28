[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param([string] $StateFile = '')

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($StateFile)) { $StateFile = Join-Path $repoRoot 'local\greg-hybrid-live-state.local.json' }
& (Join-Path $PSScriptRoot 'restore-live.ps1') -StateFile $StateFile -WhatIf:$WhatIfPreference -Confirm:$false
