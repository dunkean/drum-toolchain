# Capture Workflow

## Master resolution

Capture the master library at **48 kHz, stereo, 32-bit float WAV**. This is the
unchanged source for all later targets; it is not a DDrum4 export. The audio
interface determines the real converter resolution, while the float WAV avoids
an additional 16-bit quantisation step in the capture tool. Generate compact
DDrum4 and initial DrumGizmo files as separate, reproducible derivatives from
these masters.

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

When a preset revision changes only a few routes or gains, probe those exact
articulations first with repeatable `--only instrument.articulation` options.
For example:

```powershell
drum-sampler calibrate <usual arguments> `
  --only tom2.electronic `
  --only rim1.rimshot `
  --only snare1.deftones
```

Selectors must match the saved session exactly. Unknown names fail before any
MIDI is sent. Successful targeted WAVs use the same fingerprinted probe cache
as the later full calibration, so the complete pass reuses them instead of
recording them twice. Explicit capture and preset-loaded confirmations remain
mandatory.

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

1. Create a fresh proof session using
   `loopback:OUT 3-4 (BEHRINGER UMC 404HD 192k)`. Set SD3's shared Windows
   audio output to UMC `OUT 3-4`; do not patch an interface output to an
   interface input. Record one crash hit at velocity 110 for ten seconds and
   confirm waveform onset, no clipping, digital silence before the hit, and an
   audible decay past four seconds before continuing.
2. `sd3-djentle-beast-long-tail-cymbals.json` captures the two primary
   crashes at five mandatory velocities (24, 56, 88, 110, 127), three round
   robins each. It then captures the ride and secondary cymbals at reduced
   density. Its raw stereo material is also the DrumGizmo source.
3. Build each chosen DDrum4 crash with `ddrum4_cymbal_flagship`, never with
   the compact cymbal profile. Measure its real encoded block count, transfer
   it to an unused sound ID, and record a module render before accepting it.

The saved device indices and virtual-port suffixes are historical evidence,
not configuration. Re-list them immediately before capture. For the digital
route, the current capture name is exactly
`loopback:OUT 3-4 (BEHRINGER UMC 404HD 192k)` and the current MIDI output is
`out_WORLDE`. The shared WASAPI endpoint runs at 48 kHz. SD3 must use a shared
Windows driver during capture; restore ASIO afterwards for the low-latency
playing profile.

### First long-tail diagnostic — 2026-08-10

The route itself passed: two new stereo raw WAVs were recorded for 10.2
seconds without clipping. However, the current SD3 note selection must not be
used for the flagship bank yet. Applying the flagship profile yielded only
2.68 seconds for `crash_main_1` (note 49, velocity 110) and 1.93 seconds for
`crash_main_2` (note 57, velocity 110). The complete session remains
**planned, not executed**. First select or configure SD3 articulations whose
source has a musical decay beyond four seconds; then repeat the one-hit proof
and only then capture the complete grid.

Holding note 49 for 3 seconds before its Note Off only increased the prepared
duration to 2.83 seconds. The current result is therefore not caused primarily
by the sampler's normal 100 ms MIDI gate. Keep the short gate for the eventual
batch unless the newly selected SD3 articulation proves otherwise.
