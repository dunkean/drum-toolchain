[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$usbipdCommand = Get-Command usbipd -ErrorAction SilentlyContinue
$usbipdPath = if ($usbipdCommand) {
    $usbipdCommand.Source
} else {
    $installedPath = Join-Path $env:ProgramFiles 'usbipd-win\usbipd.exe'
    if (Test-Path -LiteralPath $installedPath) { $installedPath } else { $null }
}
$midiDevices = @(Get-PnpDevice -PresentOnly | Where-Object {
    $_.FriendlyName -match 'UMC|eDRUMin|DDTi|Arduino|TriggerIO|DDrum|CH340'
} | ForEach-Object {
    [ordered]@{
        status = $_.Status
        class = $_.Class
        name = $_.FriendlyName
        instance_id = $_.InstanceId
    }
})

$report = [ordered]@{
    kind = 'wsl-usb-status-report'
    schema_version = 1
    timestamp_utc = [DateTime]::UtcNow.ToString('o')
    usbipd_available = $null -ne $usbipdPath
    windows_midi_devices = $midiDevices
    note = 'Read-only report. Attach only USB MIDI controllers for WSL validation. Attaching the UMC404HD removes it from Windows and therefore from SD3/ASIO until detached.'
}

if ($usbipdPath) {
    $usbipdOutput = & $usbipdPath list 2>&1
    if ($LASTEXITCODE -eq 0) {
        $report.usbipd_list = @($usbipdOutput | ForEach-Object { $_.ToString() })
    } else {
        $report.usbipd_error = @($usbipdOutput | ForEach-Object { $_.ToString() })
    }
} else {
    $report.usbipd_error = @('usbipd-win is not installed. Install dorssel.usbipd-win from an elevated Windows terminal.')
}

$report | ConvertTo-Json -Depth 5
