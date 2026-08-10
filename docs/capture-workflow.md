# Capture Workflow

## Observed audio devices — 2026-08-09

The UMC404HD exposes physical inputs `IN 1-2`, `IN 3-4`, and `IN 1-4`, plus
their output pairs. It does **not** expose an identifiable UMC loopback input.
Therefore a capture session must not name an UMC input as an SD3 loopback while
SD3 continues to play only on UMC OUT 1/2.

Current safe routes:

| Source | MIDI trigger | Audio capture | Status |
| --- | --- | --- | --- |
| DDrum4 / external module | Explicit physical MIDI output | UMC `IN 1-2` | Wiring exists for DDrum4; backup remains required before transfer tests. |
| SD3 / VST | `out_APC`, `out_ClyphX`, or `out_WORLDE` | Host/DAW internal recording | Preferred if it preserves the existing monitoring path. |
| SD3 / VST | Same virtual MIDI output | UMC `IN 3-4` from a physical OUT 1/2 patch | Fallback; monitor on a different pair and prove no feedback. |

## Before a dense capture

Run a ten-minute stereo proof session with one articulation and at least three
velocities. Confirm that:

1. each raw file has non-silent signal and no clipping;
2. MIDI arrival and audio onset are stable enough for the intended trimming;
3. SD3 round-robin variation changes across repeated hits, where supplied;
4. monitoring does not feed the capture input back into itself.

The sampler always requires `--confirm-capture`, writes only missing raw take
names, and records the source/licensing declaration in its neutral library.
It also enforces the session's explicit `cooldown_ms` between newly captured
takes, so dense VST or module sessions do not depend on an undocumented
one-off delay. Already-complete takes remain skipped and do not add a delay.

## Current flagship cymbal sequence

The previous cymbal session is retained as evidence only: it recorded a
four-second source and its compact DDrum4 profile subsequently limited each
candidate to at most 1.75 seconds. `CYMB_995` was therefore useful for MIDI
transport proof but failed the listening test.

Use the two versioned sessions under `profiles/capture/` in this order:

1. `sd3-djentle-beast-long-tail-proof.json` records one crash hit at velocity
   110 for ten seconds. Confirm the physical SD3 OUT 1/2 -> UMC IN 3/4 patch,
   waveform onset, absence of clipping, and an audible decay past four
   seconds before continuing.
2. `sd3-djentle-beast-long-tail-cymbals.json` captures the two primary
   crashes at five mandatory velocities (24, 56, 88, 110, 127), three round
   robins each. It then captures the ride and secondary cymbals at reduced
   density. Its raw stereo material is also the DrumGizmo source.
3. Build each chosen DDrum4 crash with `ddrum4_cymbal_flagship`, never with
   the compact cymbal profile. Measure its real encoded block count, transfer
   it to an unused sound ID, and record a module render before accepting it.

The saved device indices are currently valid only for this PC: `out_WORLDE 2`
and UMC input `2` (IN 3-4). Re-list devices immediately before capture if the
interface topology changed.

### First long-tail diagnostic — 2026-08-10

The route itself passed: two new stereo raw WAVs were recorded for 10.2
seconds without clipping. However, the current SD3 note selection must not be
used for the flagship bank yet. Applying the flagship profile yielded only
2.68 seconds for `crash_main_1` (note 49, velocity 110) and 1.93 seconds for
`crash_main_2` (note 57, velocity 110). The complete session remains
**planned, not executed**. First select or configure SD3 articulations whose
source has a musical decay beyond four seconds; then repeat the one-hit proof
and only then capture the complete grid.
