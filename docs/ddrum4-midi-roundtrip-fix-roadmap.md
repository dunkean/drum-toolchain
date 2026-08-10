# DDrum4 MIDI Round-Trip Fix Roadmap

Status: design and evidence hand-off for the next agent. Do not add pad signal
conditioning to the Arduino. Trigger noise, false pressure, sensitivity and
crosstalk must be corrected on the DDrum4 and the physical pad.

## Required topology and invariant

Keep the permanent dual-output topology:

```text
DDrum4 MIDI OUT -> shield MIDI IN
                    +-> hardware THRU -> UMC MIDI IN -> PC / modernizer
                    +-> Arduino RX -> mapping -> shield MIDI OUT -> DDrum4 MIDI IN
```

Hardware THRU must remain a byte-transparent PC feed. Arduino OUT is the
standalone DDrum4 renderer feed. Neither role may be removed to simplify the
other one.

The Arduino may translate declared source notes to declared nested target
notes. It must not add trigger thresholds, debounce, sensitivity correction,
velocity smoothing, pressure heuristics, or automatic pad calibration.

## Verified DDrum4 SE MIDI contract

Primary reference: [DDrum4 SE V1.5x owner manual](https://images.thomann.de/pics/atg/atgdata/document/manual/123249_manual.pdf),
especially printed pages 21-24 and the MIDI implementation chart on printed
page 34. A French DDrum4 manual is also stored locally under the legacy
project's `public/CLAVIA-DDRUM-MANUALS` directory.

1. The selected MIDI channel is used for both transmission and reception.
2. `Note #` is explicitly the number each channel transmits **and responds
   to**. Positive-velocity Note On is therefore symmetric; the DDrum4 does not
   require a different note encoding merely because the event arrives at MIDI
   IN.
3. `Note P` transmits pad position as 1, 2, 4 or 8 consecutive notes beginning
   at `Note #`. The receiver/nested position behavior still needs an exhaustive
   hardware sweep, but the successful note-18 POC already proves that a
   consecutive position note can select DDrum4 audio.
4. `A.ON/A.OF` (`R.On/R.OF` on the older/French display documentation)
   controls both transmission and reception of key aftertouch. Key aftertouch
   is supported in both directions. It must not be discarded as a final
   workaround because it carries pressure/choke expression.
5. `Local Off` is explicitly designed for a sequencer/computer to echo played
   notes back to DDrum4 MIDI IN. The round trip is therefore a supported use
   case, not an unsupported hack.
6. The only documented MIDI Thru mode is `P.TH`, and it applies to Program
   Change. The manual does not document general soft-through of received Note
   or Aftertouch events to MIDI OUT. Do not assume that the DDrum4 itself
   re-emits performance input until the bench test below proves it.
7. The MIDI implementation chart shows the important asymmetry:

   - transmitted release: Note On with velocity zero (`9n 00` semantics);
   - recognized Note On: velocity 1-127;
   - Note Off is not recognized.

   The current adapter normalizes incoming Note On velocity zero to an internal
   `NoteOff` and historically emitted status `0x80`. That is not a DDrum4
   receive requirement. Standalone DDrum4 output must emit no release message
   for one-shot notes unless a future hardware proof contradicts the chart.
8. Program Change is deliberately asymmetric/special: values select kits and
   palettes. It remains disabled in this POC and belongs to the later scene
   roadmap.

Conclusion: the owner's assertion is partly correct only for release/status
details and special control messages. Positive Note On, channel, note number,
velocity and key aftertouch are the same performance vocabulary in both
directions.

## Current implementation — 2026-08-10

The Uno was reflashed with the minimal direct-DIN bridge after its native core
tests, 44 Python tests and an Uno build passed. It has deliberately **no echo
queue**, timeout, duplicate-event suppression, trigger threshold, debounce or
aftertouch filter.

- Positive Note On is mapped only by the generated nested contract.
- Polyphonic aftertouch is mapped to the same declared destination note and
  retains its value.
- MIDI `0x80` and Note On velocity zero are consumed in the standalone
  one-shot route, because DDrum4 does not recognize `0x80` as a receiver.
- Hardware THRU remains the raw PC feed; the firmware Bypass mode preserves
  input events for a non-DDrum destination.

The genuine cymbal’s tail, velocity coverage and repeatability were still not
acceptable. That is now explicitly a module/pad calibration and `CYMB_995`
matrix question, not evidence for a DDrum4 note echo. Preserve the user's
unrelated untracked `stl/` directory.

## Phase 1 — prove or reject DDrum4 performance soft-through

This is the first gate. Do not tune the echo window by ear.

1. Leave the pad untouched.
2. Put the bridge in a diagnostic silent-input mode so a returned event cannot
   be retransmitted.
3. Emit from Arduino OUT one unique, harmless event at a time to DDrum4 IN:
   positive Note On, zero-velocity Note On, and key aftertouch. Use a note that
   is not assigned to audible kit content.
4. Record DDrum4 OUT through the shield hardware THRU and UMC MIDI IN with
   timestamps.
5. Repeat at least 100 times per event type and under a short MIDI burst.
6. Record whether the event is absent, byte-identical, transformed, or delayed.

Acceptance:

- If no performance event is returned, remove/disable the echo queue from the
  production direct-DIN profile. The earlier message flood then belonged to
  the temporary PC/loopMIDI relay, not the module.
- If events are returned, retain only causal echo cancellation: consume one
  byte-identical event only when it matches an event actually emitted by the
  Arduino and arrives within the measured maximum round-trip time plus a small
  fixed margin. No generic repeated-value filter is allowed.
- The cancellation path must never delay outbound performance events.

Store the raw trace and a machine-readable result in a diagnostic artifact;
do not rely on LED appearance as proof.

## Phase 2 — implement the minimal DDrum4 wire adapter

The production standalone adapter must be deliberately boring:

1. Preserve positive Note On velocity exactly unless an explicit nested route
   maps it into a documented velocity window.
2. Map position notes only through the generated bank contract.
3. Map key aftertouch to the same destination note and preserve its value
   exactly.
4. Treat source Note On velocity zero as release metadata. Do not emit MIDI
   Note Off status `0x80` to the DDrum4 and do not emit zero-velocity Note On
   unless a receiver test proves a need.
5. Keep Program Change disabled for the POC.
6. Keep unrelated CC and system traffic on an explicit allow/drop policy; do
   not reinterpret it.
7. Keep Bypass behavior separate from the DDrum4 renderer. Hardware THRU is
   already the authoritative raw PC path.

Required tests:

- velocity identity at 1, 2, 63, 64, 126 and 127;
- all declared Note-P branches;
- repeated identical Note On events, proving none are discarded by the bridge;
- aftertouch value identity and correct note mapping;
- no `0x80` or `0x90 velocity 0` emitted in the one-shot target profile;
- a 10-minute maximum-density replay without queue growth, duplicates or lost
  original events.

## Phase 3 — calibrate the module and pad, outside Arduino

No firmware workaround is authorized in this phase.

1. Use the genuine DDrum cymbal on the documented pressure-capable CYMB2
   input, with trigger type `CYb`.
2. Start from `DYN = 0`; set input sensitivity using the DDrum4 sensitivity
   procedure and its input LED, then set `THRES` only high enough to reject
   false triggers.
3. With `Local On`, `A.ON/R.On`, Arduino output inactive, and a known-good
   sound, verify 100 ordinary hits plus deliberate chokes. This establishes
   whether the pad/module itself produces clean pressure data.
4. Record the raw Note On, zero-velocity Note On and aftertouch stream through
   hardware THRU at soft, medium and hard hits and during deliberate choke.
5. Only after Local-On behavior is clean, repeat under `Local Off` through the
   minimal adapter.

If Local-On behavior fails, repair calibration, cable, pad or trigger input.
Do not compensate in Arduino. If Local-On is clean but the byte-faithful return
is not, the trace is a protocol bug fixture for Phase 2.

## Phase 4 — repair `CYMB_995` independently of transport

The current flagship cymbal builder calls
`snare_velocity_layers(len(samples))`. That function returns a prefix of seven
fixed reference rows. For a four-sample cymbal it takes rows 1-4 of a
seven-layer layout; it does not generate a four-layer, full-range velocity
crossfade. This is a design bug until a BUTTON sweep proves otherwise.

1. First build a one-sample, one-layer flat-gain cymbal diagnostic sound. It
   must respond across BUTTON velocities 1-127 and is the transport reference.
2. Decode/verify the eight gain-velocity control points using DDrum4UI visual
   inspection and controlled BUTTON sweeps.
3. Replace prefix slicing with an N-layer curve generator or reviewed layouts
   for each supported sample count. Every one of the eight velocity points
   must have audible coverage; adjacent layers may crossfade but must not leave
   gaps.
4. Add validation that rejects an all-zero active layer and rejects any
   velocity point with no active gain contribution.
5. Rebuild the four-layer crash under a new disposable sound ID. Do not
   overwrite the current evidence artifact.
6. On the module set the assigned channel to `VARIATION 1` and `DECAY 100`.
   The SE manual defines 100, not 99, as the full original sample length.
7. Run a panel BUTTON sweep at 1, 16, 32, 48, 64, 80, 96, 112 and 127 before
   testing any pad. Record level, chosen layer and audible tail.
8. Require the 6.5-second source tail to remain musical on the module. A sound
   failure must not be diagnosed as a MIDI-loop failure.

## Phase 5 — end-to-end acceptance

Use the unchanged dual-output cabling and DDrum4 `Local Off`, aftertouch on.

- 200 single cymbal hits across the useful dynamic range: no loss or duplicate;
- fast repeated hits and simultaneous different pads: no saturation;
- positional note sweep: every declared nested branch deterministic;
- deliberate choke: preserved once, with no spontaneous choke;
- raw hardware THRU trace matches the DDrum4 performance output;
- Arduino output contains only the declared mapping and no unsupported release;
- crash tail and dynamics pass independently through the corrected sound;
- no manual cable swap between standalone and PC observation.

Only after these gates pass should the diagnostic CYMB2 route be generalized
to every native DDrum4 pad and merged with DDTi/eDRUMin routing.
