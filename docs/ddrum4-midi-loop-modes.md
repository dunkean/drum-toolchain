# DDrum4 MIDI loop modes

## Permanent physical wiring

```text
DDrum4 MIDI OUT -> Arduino shield MIDI IN
Arduino shield MIDI THRU -> UMC404HD MIDI IN -> PC / modernizer
Arduino shield MIDI OUT -> DDrum4 MIDI IN
```

The installed shield's THRU port is a hardware copy of the received DDrum4
stream. It was proven at the UMC with channel 12 note events and DDrum4
poly-aftertouch. It does not use Arduino firmware or its TX output.

## Why modes are necessary

In `L.OF`, DDrum4 needs the Arduino to return a note through MIDI IN before it
plays. The original physical-pad event is always visible on the shield's
hardware THRU. DDrum4 performance soft-through of an Arduino-returned event
has **not** been directly proven; the earlier duplicate flood came from a PC /
loopMIDI relay. Consequently the flashed bridge contains no event queue or
time-based echo guard: such a guard could swallow a genuine subsequent hit.

| Mode | DDrum4 Local | Arduino DIN OUT | PC input policy | Use |
| --- | --- | --- | --- | --- |
| `PC_CLEAN` | `L.ON` | Silent | Accept raw THRU stream. | SD3/DrumGizmo with maximum native DDrum4 expressivity and no duplicate return. |
| `STANDALONE` | `L.OF` | Nested-map events to DDrum4. | Monitor only; do not feed that stream to SD3. | Computer-free DDrum4 bank. |
| `DUAL` | `L.OF` | Nested-map events to DDrum4. | Not offered until a direct DIN trace proves the DDrum4 return behavior. | Future DDrum4 bank and SD3 together. |
| `PC_BYPASS` (future) | `L.OF` | Return original events unchanged. | Not offered until a direct DIN trace proves the DDrum4 return behavior. | Same fixed cabling without changing Local Control. |

`PC_CLEAN` and `STANDALONE` are immediately safe with the existing bridge.
`DUAL` and `PC_BYPASS` first require a direct-DIN trace; only if it proves a
byte-identical return may the modernizer gain a causal, bounded return filter.

## Return-echo filter contract (future modernizer)

The filter is not a generic time-based MIDI de-duplicator. It may only be
implemented after the direct-DIN trace proves a return event. It receives the
generated routing contract from the bank builder and can predict the exact
DDrum4 event returned for each raw event. Only a byte-identical event within
the measured physical return interval may be dropped. All physical-pad events
stay available to SD3, including positional poly-aftertouch.

The filter runs only in `DUAL` or `PC_BYPASS`; it is off in `PC_CLEAN`.
Metrics must display matched returns, expired expectations and unmatched
messages so a bad configuration cannot silently eat expressive input.

## Mode selection

The firmware now accepts a reserved bridge-local message: **channel 16 / CC
119**. It is consumed by the Arduino and never emitted from Arduino OUT; the
hardware THRU copy still reaches the PC. Its value selects the output role:

| CC119 value | Arduino mode | Intended DDrum4 Local state |
| ---: | --- | --- |
| 0–41 | `NESTED` | `L.OF` |
| 42–83 | `SILENT` | `L.ON` for PC-clean |
| 84–127 | `BYPASS` | `L.OF`, only with the future PC return filter |

This requires the forthcoming firmware flash. A debounced physical mode
button with a visible mode LED remains a later convenience feature.

A mode change affects future messages only; it must release or flush no notes
artificially. `L.ON` / `L.OF` remains a DDrum4 module setting until its remote
control protocol is independently confirmed.
