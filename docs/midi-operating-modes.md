# MIDI operating modes: standalone DDrum4 and PC/SD3

## Decision

The DDrum4 has two deliberately separate operating modes, but they can use
one permanent cable layout **if the installed shield's DIN `THRU` is confirmed
to be a raw hardware copy of DIN `IN`**. Its clone documentation is ambiguous;
the required harmless bench test is in
[`hardware/arduino-midi-breakout-shield.md`](hardware/arduino-midi-breakout-shield.md).

| Mode | DDrum4 Local | Primary sound engine | DDrum4 MIDI OUT destination | Arduino role |
| --- | --- | --- | --- | --- |
| `standalone-nested` | `L.OF` | DDrum4 | Arduino input, via the MIDI merger | translate all sources to nested DDrum4 branches; suppress module echo |
| `pc-sd3-raw` | `L.ON` | SD3 / modernizer | UMC MIDI IN directly | not in the DDrum4 event path |

In `pc-sd3-raw`, DDTi and eDRUMin continue over USB directly to the PC. The
DDrum4 MIDI stream reaches the modernizer through UMC MIDI IN unchanged. This
preserves the module's native positional notes, pressure, choke, timing, and
velocity without an Arduino parser/re-emitter in between.

## Wiring

### Target permanent one-cable layout (after the THRU test passes)

```text
 DDrum4 MIDI OUT -> Arduino MIDI IN
 Arduino MIDI THRU -> UMC MIDI IN -> PC / modernizer
 Arduino MIDI OUT ------------------------> DDrum4 MIDI IN
```

If validated, the shield's MIDI THRU is an electrical/raw copy of MIDI IN, not
a merger. It gives the PC a raw DDrum4 copy at all times while the Arduino
receives that same stream. The Uno never has to parse and reproduce the PC
copy for SD3.

### Standalone nested (after MIDI merger arrives)

```text
DDTi MIDI OUT -------------------------------+
eDRUMin DIN MIDI OUT ------------------------> merger -> Arduino MIDI IN
DDrum4 pads -> DDrum4 MIDI OUT --------------+
DDTi MIDI OUT --------------------------------> merger input
eDRUMin DIN MIDI OUT -------------------------> merger input

Arduino MIDI OUT -> DDrum4 MIDI IN -> DDrum4 headphones/outputs
```

The merger must feed Arduino MIDI IN with all three sources. The Arduino THRU
still forwards the raw merged input to UMC for optional monitoring. Use `L.OF`;
the Arduino echo guard is required because the tested module path can
retransmit MIDI-IN events through MIDI OUT.

### PC / SD3 raw

```text
DDrum4 pads -> DDrum4 MIDI OUT -> UMC MIDI IN -> modernizer -> SD3
DDTi USB -----------------------------------------------> modernizer / SD3
eDRUMin USB --------------------------------------------> SD3 (or modernizer)
```

Use `L.ON`. The Arduino remains connected but is in `PC_SILENT` mode: it
consumes no source events and sends no MIDI. The raw DDrum4 copy arriving from
shield THRU at UMC is therefore untouched. No physical reconnection is
required.

## Why an Arduino mode button alone is insufficient

The current Uno MIDI shield has one programmable DIN input and one
programmable DIN output, plus the dedicated THRU copy. A firmware button can
therefore select `STANDALONE` or `PC_SILENT` without changing cables. UMC
always receives the raw DDrum4 stream from hardware THRU; Arduino OUT stays
permanently connected to DDrum4 MIDI IN.

If a future one-cable selector is desired, add one of these hardware changes:

If the shield's THRU proves not to be a raw hardware copy in the bench test,
the fallback is a MIDI Thru distributor on DDrum4 MIDI OUT, yielding one copy
for UMC and one for Arduino.

Only then does a front-panel Arduino button make sense:

- `STANDALONE`: generated nested map -> DDrum4 output;
- `PC_SILENT`: no Arduino output; UMC already receives raw DDrum4 MIDI through
  the hardware THRU.

If the test fails, a compact powered MIDI-Thru distributor is the only missing
hardware: `DDrum4 OUT -> Thru IN`, with one output to Arduino IN and one to
UMC IN. It preserves exactly the same operating modes and cabling thereafter.

The current UMC + MIDI4x4 + PC developer relay remains useful while the final
fixed cabling is not yet connected.
