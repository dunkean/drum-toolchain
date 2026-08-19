# DDTi USB/MIDI identification

Date observed: 2026-08-19.  This document records operating-system facts only;
it does not establish the DDTi SysEx protocol.

## Connected candidate

| Fact | Observed value | Confidence |
| --- | --- | --- |
| Module serial supplied by owner | `2016040855` | CONFIRMED (physical label/user report) |
| USB VID | `13B2` | CONFIRMED (Windows PnP) |
| USB PID | `0021` | CONFIRMED (Windows PnP) |
| USB revision | `0001` | CONFIRMED (Windows hardware ID) |
| USB parent | `USB\\VID_13B2&PID_0021\\7&7F8D4A1&0&1` | CONFIRMED (Windows PnP) |
| USB class | Composite USB device | CONFIRMED (Windows PnP) |
| Audio/MIDI function | `USB\\VID_13B2&PID_0021&MI_00\\8&2EE3AC2E&1&0000` | CONFIRMED (Windows PnP) |
| Driver | Microsoft USB Audio Device (`wdma_usb.inf`) | CONFIRMED (Windows driver inventory) |
| MIDI input | `TriggerIO 30` | CONFIRMED (`mido.get_input_names()`) |
| MIDI output | `TriggerIO 10` | CONFIRMED (`mido.get_output_names()`) |
| Product name reported to MIDI API | `TriggerIO` | CONFIRMED |
| Manufacturer string | not exposed by Windows driver | UNKNOWN |
| USB descriptor serial string | not exposed by Windows driver | UNKNOWN |
| USB interfaces/endpoints | not exposed by available Windows PnP APIs | UNKNOWN |

The MIDI endpoint and VID/PID are treated as a *candidate legacy DDTi* because
they match the connected module context.  The software must not infer the
firmware version, model generation, command bytes, or configuration layout
from these identifiers alone.

## Read-only inventory procedure

```powershell
$env:PYTHONPATH = 'apps/ddti/src'
python -m ddti devices
python -m ddti info
```

Both commands query Windows/MIDI enumeration and do not open a MIDI output.
For a refreshed raw Windows inventory, use:

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object { $_.InstanceId -match 'VID_13B2&PID_0021' } |
  Format-List *
```

## Safety status

- No firmware, bootloader, or write operation has been attempted.
- No SysEx request has been sent.
- No DDTi dump has yet been captured in this repository.
- The next permitted hardware action is a user-initiated panel dump captured
  by the receive-only `ddti dump` command.
