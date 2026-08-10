# Arduino MIDI Breakout Shield — hardware contract

## Scope and identification

This document describes the installed generic Arduino Uno MIDI breakout shield,
sold as AliExpress product `1005003953829918`. It is a clone-family design
similar to the historical LinkSprite/SparkFun MIDI breakout boards, not a
guaranteed electrically identical product. It is installed on an Uno R3
compatible board with a CH340 USB serial interface.

The product page was supplied by the owner. Its media page could not be fetched
reliably during documentation, so the board itself and the bench test below
remain the source of truth. Related vendor-family documentation is retained as
context, not as proof for this exact clone:

- [LinkSprite MIDI Shield for Arduino](https://www.linksprite.com/wiki/index.php?title=MIDI_Shield_for_Arduino)
- [SparkFun BOB-09598 source schematic](https://raw.githubusercontent.com/sparkfun/MIDI_Breakout/master/Hardware/MIDI_Breakout.sch)
- [Seller product page](https://fr.aliexpress.com/item/1005003953829918.html)

## Observed connections and operating rule

| Connection / feature | Intended role | Confidence |
| --- | --- | --- |
| DIN `MIDI IN` | Receives MIDI for the Uno UART through an optocoupler. | High |
| DIN `MIDI OUT` | Transmits the Uno UART output to an external MIDI input. | High |
| DIN `MIDI THRU` | Hardware copy of the optocoupler's received MIDI signal, through its own MIDI current-loop output circuit. It bypasses Arduino TX and firmware. | Proven on the installed shield |
| RUN / PGM switch | `PGM` allows reliable USB/CH340 programming; `RUN` connects the UART to the MIDI hardware. | High, observed |
| Uno UART pins | MIDI uses the Uno hardware UART (D0/RX and D1/TX) at 31,250 baud. USB serial and MIDI cannot be used as independent data paths while the switch connects the MIDI circuit. | High |

The clone-family board may also expose buttons, LEDs and analogue controls.
Their pin assignments must be read from the physical PCB before firmware uses
them; they are not part of the present routing contract.

## Required flashing procedure

1. Set the shield switch to `PGM`.
2. Upload through the Uno's CH340 USB port (`COM3` in the current Windows
   installation).
3. Set the switch back to `RUN`.
4. Reset the Uno once, then test MIDI.

Do not leave it in `PGM` when testing performance MIDI: the DIN MIDI connection
is not in its intended run configuration.

## THRU validation test — passed

This test neither sends MIDI to the DDrum4 nor changes its sound memory.

### Temporary cables

```text
DDrum4 MIDI OUT  -> shield MIDI IN
shield MIDI THRU -> UMC MIDI IN

Leave shield MIDI OUT disconnected for this test.
```

Set the shield to `RUN`. On the DDrum4 set `L.OF` for the test so a struck pad
is certainly emitted as MIDI. Strike the currently known CYMB2/snare test pad
and inspect the UMC MIDI input on the PC.

### Observed result — 2026-08-10

With `DDrum4 OUT -> shield IN` and `shield THRU -> UMC IN`, the passive PC
monitor received DDrum4 channel 12, note 17 events and its poly-aftertouch
stream. No Arduino MIDI OUT was connected for this test. This proves that THRU
is an independent raw hardware output on the installed board.

### Interpretation

| Result | Meaning | Next action |
| --- | --- | --- |
| Raw event arrives | THRU is a usable hardware duplicate. | **Observed: use the fixed wiring below.** |
| No event arrives | THRU may be unpowered, connected to the wrong DIN socket, or not fitted. | Check board/cables before assuming a clone difference. |
| Event changes or depends on firmware | It is not suitable for raw SD3 input. | Use an independent MIDI-Thru distributor. |

## Fixed parallel wiring — no additional hardware

```text
DDrum4 MIDI OUT -> shield MIDI IN
                    +-> shield MIDI THRU -> UMC MIDI IN -> PC / modernizer
                    +-> Arduino firmware

Arduino MIDI OUT ------------------------------------------> DDrum4 MIDI IN
```

This is intentionally one permanent wiring arrangement.

- **PC / SD3 raw mode:** DDrum4 `L.ON`; Arduino is `PC_SILENT` and emits no
  MIDI. The UMC obtains untouched DDrum4 events via hardware THRU. DDTi and
  eDRUMin stay
  directly connected by USB to the PC.
- **Standalone nested mode:** DDrum4 `L.OF`; Arduino maps incoming events to
  DDrum4 nested notes and emits them on its DIN OUT. Hardware THRU may simultaneously
  feed the PC for monitoring, but the PC must not return those events to the
  DDrum4.

The Arduino mode selector is a future firmware feature. It can select what
the Arduino transmits, but it cannot by itself change the DDrum4's `L.ON` / 
`L.OF` setting; that remains a manual module setting until a safe DDrum4
configuration command has been researched and verified.

## Future merger constraint

When the external MIDI merger is added, it must combine DDrum4 OUT, DDTi DIN
OUT and eDRUMin DIN OUT *before* Arduino MIDI IN for standalone nested play.
Hardware THRU is not a merger and it cannot combine multiple MIDI outputs.

Never connect two MIDI OUT sockets directly to one MIDI IN socket. Never feed
the UMC/PC monitor output back to DDrum4 MIDI IN in standalone mode; that would
create a MIDI feedback loop.
