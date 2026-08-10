# DDrum4 Local-OFF central routing

Status: proposed architecture. It is intentionally **not** a live module configuration yet.

## Why this is needed

A DDrum4 physical pad with `Local ON` plays its sound immediately. It cannot
be made, per hit, to select an arbitrary variation in a shared sound from the
Arduino. Therefore the original direct connection of `DD crash 2 -> CYMB 2`,
for example, prevents CYMB 2 from also being a flexible nested destination.

The DDrum4 SE manual documents the intended alternative: with `Local OFF`, a
physical pad transmits MIDI OUT but does not play locally; an external device
echoes a selected MIDI event back to MIDI IN. This is exactly the ownership
boundary required for the Arduino to select a DDrum note / Note-P position / a
velocity window for every pad, including pads physically connected to the
DDrum4.

## Proposed signal ownership

```text
DDrum4 pads -- DDrum4 MIDI OUT --+
DDTi ------------------------------> MIDI merger --> Arduino bridge --> DDrum4 MIDI IN
eDRUMin (DIN MIDI OUT) ------------+
```

The Arduino has one MIDI output only: DDrum4 MIDI IN. It does not send the
selected output back to the merger. Each input source must use a distinct MIDI
channel, so the bridge can distinguish otherwise-identical note numbers.

Some tested DDrum4 Local-OFF paths retransmit a received MIDI-IN event through
MIDI OUT. The Arduino firmware consequently has a bounded immediate-echo
guard: it remembers its own outgoing messages and consumes a matching return
before route lookup. This is an in-memory comparison, not a delay or a MIDI
timer; it adds no audible latency. The guard must remain enabled for every
standalone Local-OFF profile.

Suggested channel reservation, pending a trace from each device:

| Source | Proposed channel | Role |
| --- | ---: | --- |
| DDTi | 10 | existing trigger source |
| eDRUMin | 11 | expressive snare/hat/cymbals |
| DDrum4 Local-OFF pads | 12 | native DDrum4 trigger inputs |
| Arduino -> DDrum4 | 12 | final sound-bank input; this must match DDrum4 MIDI receive channel |

The DDrum4 uses one MIDI channel for both transmission and reception, so its
source and the Arduino's return channel are deliberately both 12. In `Local
OFF`, locally generated pad hits are transmitted and incoming notes play the
module; normal note data is not echoed back again. The numbers are
reservations, not verified settings. The production profile is
only generated after recording a MIDI trace of every source; the Arduino must
not be flashed with guessed notes.

## Slot allocation made possible by Local OFF

This keeps the user’s ten DDrum4 slot groups while making even the native
DDrum4 pads routable. It is a quality-first candidate, not a final note map.

| Slot | Source pads routed by Arduino | Nested strategy |
| --- | --- | --- |
| Kick | DDrum4 kick | single core sound / velocity layers |
| Snare | eDRUMin main snare | positional + velocity layers |
| Rim | DDrum4 rim, DDTi rim 2 | two fixed branches |
| Tom high | DDTi tom 1 + tom 2 | two Note-P positions |
| Tom mid | DDTi tom 3 + snare 2 | two Note-P positions |
| Tom low | DDTi ride bow/bell/edge | three Note-P positions |
| Perc | DDrum4 old hi-hat | fixed percussion branch |
| Cymbal 1 | eDRUMin crash double 1 + 2 | two Note-P positions |
| Cymbal 2 | DDrum4 crash 2; DDTi crash 1, half-crash, splash, DD crash 1 | up to eight positions |
| Hi-hat | eDRUMin ZEITGEIST pad + pedal | direct CC4 plus Note-P articulations |

This resolves the specific `CYMB 2` conflict: the physical DDrum4 crash no
longer directly triggers CYMB 2. The bridge assigns it a reserved CYMB-2
position, while the other pads select different positions.

## Required proof before live adoption

1. Save the current DDrum4 configuration externally (already done).
2. On the DDrum4, enable `Local OFF`; do not use `L.PD`, which disables pads.
3. Set / confirm its MIDI OUT channel, then capture a short trace for kick,
   rim, and DD crash 2. Confirm those source events arrive at the Arduino.
4. Flash only a three-route diagnostic profile that echoes those three pads to
   three harmless DDrum4 test sounds.
5. Verify exactly one sound per strike, no feedback loop, and acceptable
   latency. Only then map all pads and load the nested bank.

If a source cannot output on a distinct channel, it needs a separate Arduino
input port or a channel-remapping stage before the merger. A single merged DIN
stream alone cannot preserve source identity when two devices emit the same
channel and note.

## Firmware support

`ddrum4-midi-bridge` now builds its allowed Program-Change sources from every
entry in `midi.sources`; it is no longer hard-coded to only DDTi and eDRUMin.
Generic note routes were already source-channel based. This makes a declared
`ddrum4` source a normal route producer rather than a special case.

## Hardware evidence — 2026-08-10

- With `C12` and `L.OF`, an actual snare pad temporarily connected to the
  DDrum4 CYMB2 input emitted channel 12, note 17, with observed Note-On
  velocities from 10 to 127. It also emitted polyphonic pressure messages;
  this is expected from the unsuitable temporary pad/input pairing and is not
  yet a final trigger calibration.
- A first PC-assisted relay without echo protection produced approximately
  8,883 messages in 45 seconds, proving the DDrum4 return echo exists.
- With the bounded firmware echo guard, the same test remained bounded
  (133 UMC-to-Arduino messages and 102 Arduino-to-UMC messages over 15
  seconds). The remaining traffic was pressure-rich source data, not an
  escalating loop. No DDrum4 kit sound assignment was assumed, so this is a
  MIDI transport proof rather than an audio audition.
