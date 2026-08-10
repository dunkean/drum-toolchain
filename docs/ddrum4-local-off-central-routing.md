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

The temporary PC-assisted Local-OFF relay produced a feedback path, but that
test did not isolate the DDrum4 from loopMIDI/PC routing. The SE manual only
documents MIDI Thru for Program Change (`P.TH`), not for Note or Aftertouch.
General DDrum4 MIDI-IN re-emission is therefore unproven. The production
profile must enable causal echo cancellation only if the direct-DIN test in
`ddrum4-midi-roundtrip-fix-roadmap.md` records a returned performance event.

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
module. The numbers are reservations, not verified settings. The production profile is
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
  8,883 messages in 45 seconds. This proves that the complete temporary relay
  topology fed back; it does not identify the DDrum4 as the device performing
  MIDI soft-through.
- With the bounded firmware echo guard, the same test remained bounded
  (133 UMC-to-Arduino messages and 102 Arduino-to-UMC messages over 15
  seconds). The remaining traffic was pressure-rich source data, not an
  escalating loop. No DDrum4 kit sound assignment was assumed, so this is a
  MIDI transport proof rather than an audio audition.
- **End-to-end nested branch POC passed:** a temporary mesh snare pad on the
  CYMB2 input was configured `C12`, `Local OFF`, `Note # 17`, `Note P 2` and
  threshold 40. Its observed C12/note-17 events went through the PC relay to
  the Arduino; the initial diagnostic returned C12/note-18 at fixed velocity
  110; the DDrum4 played the CYMB2-assigned `CYMB_995` through its headphones.
  The final live audit recorded both Note-On and Note-Off translations,
  including source velocities 44 and 127. This proves the complete pad →
  Arduino branch-selection → DDrum4 audio path. The diagnostic mapping was
  subsequently changed to preserve input velocity for dynamic-layer audition.
- `CYMB_995` is a transport/sound candidate, not an approved
  crash. Its late attack/short tail and silence below its current low velocity
  range were heard during this proof. The diagnostic therefore projects to
  velocity 110. Replacing it with a long, correctly trimmed crash and a
  position-distinct nested sound is a required sound-bank task, not a routing
  failure.
- A later trace with a genuine DDrum cymbal in `CYb` mode isolated the audio
  failure: each strike emitted C12/note 18/velocity 127, followed 23.7-25.5 ms
  later by C12/note 18/velocity 0. The adapter correctly interpreted the
  velocity-zero Note On as an internal Note Off and historically emitted MIDI
  status `0x80`. The SE MIDI implementation chart says Note Off is not
  recognized, so that output was unsupported rather than a proven cause of
  sample gating. The panel CYMB2 button only proves the local sound assignment;
  it does not exercise this MIDI return path.
- The DDrum4 Nested profile therefore preserves Note On velocity and
  polyphonic aftertouch but suppresses Note Off. This is a target-level
  one-shot policy, not pad conditioning: no threshold, curve, debounce, or
  pressure filter was added. Bypass mode still forwards Note Off unchanged for
  PC/VST use.
- The temporary exact-event queue was removed from the production bridge. It
  could retain an expectation when no return arrived, then mistake a later real
  hit with the same quantised velocity for a return. Since the DDrum4’s own
  performance soft-through is still unproven, no generic or timed
  de-duplication belongs in the live path. The direct-DIN trace gate in
  `ddrum4-midi-roundtrip-fix-roadmap.md` is required before any causal guard
  is reconsidered. `P.OF` disables Program Change and is not an echo policy.
