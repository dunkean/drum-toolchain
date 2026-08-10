# MIDI operating modes: standalone DDrum4 and PC/SD3

## Decision

The DDrum4 has deliberately separate operating modes, and the installed
shield supports a permanent parallel layout. Its hardware DIN `THRU` is an
independent raw copy of the DIN `IN` signal; it was verified by capturing
DDrum4 note and poly-aftertouch events at UMC MIDI IN. Details are in
[`hardware/arduino-midi-breakout-shield.md`](hardware/arduino-midi-breakout-shield.md).
The full return-echo contract is in
[`ddrum4-midi-loop-modes.md`](ddrum4-midi-loop-modes.md).

| Mode | DDrum4 Local | Primary sound engine | DDrum4 MIDI OUT destination | Arduino role |
| --- | --- | --- | --- | --- |
| `standalone-nested` | `L.OF` | DDrum4 | Arduino input, via the MIDI merger | translate all sources to nested DDrum4 branches; suppress module echo |
| `pc-clean` | `L.ON` | SD3 / modernizer | shield THRU -> UMC MIDI IN | `SILENT`; not in the DDrum4 return path |
| `dual` (future gate) | `L.OF` | DDrum4 + SD3 | shield THRU -> UMC MIDI IN | nested map; modernizer suppresses expected DDrum4 return echoes |

In `pc-clean`, DDTi and eDRUMin continue over USB directly to the PC. The
DDrum4 MIDI stream reaches the modernizer through UMC MIDI IN unchanged. This
preserves the module's native positional notes, pressure, choke, timing, and
velocity without an Arduino parser/re-emitter in between.

## Wiring

### Permanent one-cable layout

```text
 DDrum4 MIDI OUT -> Arduino MIDI IN
 Arduino MIDI THRU -> UMC MIDI IN -> PC / modernizer
 Arduino MIDI OUT ------------------------> DDrum4 MIDI IN
```

Hardware THRU gives the PC a raw DDrum4 copy at all times while the Arduino
receives that same stream. The Uno never has to parse and reproduce the PC
copy for SD3.

### Standalone nested (after MIDI merger arrives)

```text
DDTi MIDI OUT -------------------------------+
eDRUMin DIN MIDI OUT ------------------------> merger -> Arduino MIDI IN
DDrum4 pads -> DDrum4 MIDI OUT --------------+

Arduino MIDI OUT -> DDrum4 MIDI IN -> DDrum4 headphones/outputs
```

The merger must feed Arduino MIDI IN with all three sources. Hardware THRU
still forwards the raw merged input to UMC for optional monitoring. Use `L.OF`;
the Arduino echo guard is required because the tested module path can
retransmit MIDI-IN events through MIDI OUT.

### PC / SD3 clean

```text
DDrum4 pads -> DDrum4 MIDI OUT -> shield IN -> shield THRU -> UMC MIDI IN -> modernizer -> SD3
DDTi USB ------------------------------------------------------------------> modernizer / SD3
eDRUMin USB ----------------------------------------------------------------> SD3 (or modernizer)
```

Use `L.ON`. The Arduino remains connected but is in `PC_SILENT` mode: it
consumes no source events and sends no MIDI. The raw DDrum4 copy arriving from
hardware THRU at UMC is therefore untouched. No physical reconnection is
required.

## Arduino mode selection

The current Uno MIDI shield has one programmable DIN input and one
programmable DIN output, plus a dedicated hardware THRU copy. A firmware
button can therefore select `NESTED`, `BYPASS`, or `SILENT` without changing
cables. UMC always receives the raw DDrum4 stream from hardware THRU; Arduino OUT stays
permanently connected to DDrum4 MIDI IN.

- `NESTED`: generated nested map -> DDrum4 output;
- `BYPASS`: original input -> DDrum4 output, with the Arduino return-echo
  guard still enabled;
- `SILENT`: no Arduino output; UMC already receives raw DDrum4 MIDI through
  hardware THRU.

The bridge core implements these states and its native tests cover the
transition semantics. Firmware now reserves channel 16 / CC119 as a local
mode control: values 0–41 select `NESTED`, 42–83 select `SILENT`, and 84–127
select `BYPASS`. The control is consumed by the Arduino and never reaches the
DDrum4. It has not yet been flashed to the hardware. A physical button remains
a later convenience feature.

The current UMC + MIDI4x4 + PC developer relay remains useful while the final
fixed cabling is not yet connected.
