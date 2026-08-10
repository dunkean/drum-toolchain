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
- [Seller product page](https://fr.aliexpress.com/item/1005003953829918.html)

## Observed connections and operating rule

| Connection / feature | Intended role | Confidence |
| --- | --- | --- |
| DIN `MIDI IN` | Receives MIDI for the Uno UART through an optocoupler. | High |
| DIN `MIDI OUT` | Transmits the Uno UART output to an external MIDI input. | High |
| DIN `MIDI THRU` | Claimed by clone-family descriptions to be tied to the incoming MIDI path. Whether it is an electrically buffered copy, a firmware-dependent output, or merely a labelled tap is **unverified**. | Unverified |
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

## THRU validation test — required before fixed parallel wiring

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

### Pass condition

The UMC receives exactly the raw DDrum4 event (currently channel 12, note 17,
with the struck velocity) without relying on Arduino firmware forwarding.
The Arduino may be powered, but changing its diagnostic sketch must not be
necessary for the event to appear.

### Interpretation

| Result | Meaning | Next action |
| --- | --- | --- |
| Raw event arrives | THRU is a usable hardware duplicate. | Install the fixed wiring below. |
| No event arrives | THRU is not a usable raw duplicate, is not fitted, or needs a different implementation. | Do not rely on it; use a powered 1-in/2-out MIDI-Thru distributor. |
| Event changes, duplicates, or depends on firmware | It is not suitable for raw SD3 input. | Use the distributor fallback. |

## Fixed parallel wiring if THRU passes

```text
                          +-> shield MIDI THRU -> UMC MIDI IN -> PC / modernizer
DDrum4 MIDI OUT -> shield MIDI IN
                          +-> Arduino firmware

Arduino MIDI OUT ------------------------------------------> DDrum4 MIDI IN
```

This is intentionally one permanent wiring arrangement.

- **PC / SD3 mode:** DDrum4 `L.ON`; Arduino is `PC_SILENT` and emits no MIDI.
  The UMC obtains the untouched DDrum4 events via THRU. DDTi and eDRUMin stay
  directly connected by USB to the PC.
- **Standalone nested mode:** DDrum4 `L.OF`; Arduino maps incoming events to
  DDrum4 nested notes and emits them on its DIN OUT. THRU may simultaneously
  feed the PC for monitoring, but the PC must not return those events to the
  DDrum4.

The Arduino mode selector is a future firmware feature. It can select what
the Arduino transmits, but it cannot by itself change the DDrum4's `L.ON` / 
`L.OF` setting; that remains a manual module setting until a safe DDrum4
configuration command has been researched and verified.

## Future merger constraint

When the external MIDI merger is added, it must combine DDrum4 OUT, DDTi DIN
OUT and eDRUMin DIN OUT *before* Arduino MIDI IN for standalone nested play.
The shield THRU then mirrors that merged stream for monitoring only. It is not
a merger and it cannot combine multiple MIDI outputs.

Never connect two MIDI OUT sockets directly to one MIDI IN socket. Never feed
the UMC/PC monitor output back to DDrum4 MIDI IN in standalone mode; that would
create a MIDI feedback loop.
