# Capture Workflow

## Master resolution

Capture the master library at **48 kHz, stereo, 32-bit float WAV**. This is the
unchanged source for all later targets; it is not a DDrum4 export. The audio
interface determines the real converter resolution, while the float WAV avoids
an additional 16-bit quantisation step in the capture tool. Generate compact
DDrum4 and initial DrumGizmo files as separate, reproducible derivatives from
these masters.

## Observed audio devices — verified 2026-08-28

The active Windows shared-audio route exposes `loopback:OUT 3-4`. It has been
proved end to end by sending the campaign MIDI through `out_ClyphX 6`, playing
the fingerprinted MegaKit in SD3, recording stereo at 48 kHz, and analysing
the resulting WAV files. This endpoint is the authoritative SD3 calibration
and capture route on the current workstation. Physical UMC inputs remain for
external-module captures only and must never be substituted for this loopback.

Current safe routes:

| Source | MIDI trigger | Audio capture | Status |
| --- | --- | --- | --- |
| DDrum4 / external module | Explicit physical MIDI output | UMC `IN 1-2` | Wiring exists for DDrum4; backup remains required before transfer tests. |
| SD3 standalone | `out_ClyphX 6` | `loopback:OUT 3-4` | Current closed-loop route; proven at 48 kHz. |
| SD3 / VST in a DAW | Explicit virtual MIDI output | Host/DAW internal recording | Alternative only after a new bounded proof and recorded endpoint identity. |

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

For the current local MegaKit revision, the guarded wrapper is:

```powershell
.\scripts\calibrate-greg-hybrid.ps1 -Mode Targeted -ConfirmCapture -ConfirmPresetLoaded -ConfirmMegaKitMidiMap
.\scripts\calibrate-greg-hybrid.ps1 -Mode Full -ConfirmCapture -ConfirmPresetLoaded -ConfirmMegaKitMidiMap
```

The targeted command writes a revision-specific targeted report; only the full
command writes the canonical `calibration.json` consumed by the campaign gate.
On Windows, the guarded wrapper also verifies the running SD3 window title and
refuses capture when SD3 restored another preset revision at startup.
The `-ConfirmMegaKitMidiMap` gate additionally records the operator check that
`Kit_Metalcore_MidiMapping_Capture_V1` is active, not the portable standard-kit
map which intentionally redirects the custom note namespace.

The current wrapper targets MegaKit v23 and a fingerprinted 939-take campaign.
Its calibration report uses family-relative level gates: silence, clipping,
insufficient headroom, or a `level-fail` result prevents the full capture.
The complete v23 calibration passed all 70 declared articulations with no
technical silence, clipping, or relative-level outlier. The user approved the
musical balance on 2026-08-29 and authorized the resumable 939-take production
capture from the immutable approved preset snapshot.

The Control Center applies the same safety boundary. Before calibration or a
full capture it reads the visible SD3 window title directly, requires it to
contain the exact campaign preset name, and asks for confirmation of the MIDI
map recorded in `campaign.json`. A full capture accepts only a complete
`sd3-calibration-report/v2` for the current session and preset: targeted
probes, legacy v1 reports, missing family groups, technical failures, or level
outliers cannot unlock it. The campaign dashboard exposes each comparable
family's quietest/loudest peak, span, and outliers instead of reducing the
decision to a single status line.

Run a ten-minute stereo proof session with one articulation and at least three
velocities. Confirm that:

1. each raw file has non-silent signal and no clipping;
2. MIDI arrival and audio onset are stable enough for the intended trimming;
3. SD3 round-robin variation changes across repeated hits, where supplied;
4. monitoring does not feed the capture input back into itself.

The automatic report aligns and normalizes the first 250 ms of every accepted
take, quantizes that transient, and fingerprints it. Two repetitions declared
as round robins with the same transient fingerprint fail the campaign gate;
the report lists the exact articulation and velocity cell instead of silently
shipping a non-variation.

Both quality reports are immutable provenance gates. The full report records
the SHA-256 of `library.json` and `capture-session.json`; the composite report
records the session and MegaKit-plan hashes plus the measured SHA-256 of every
composite WAV. Control Center and the direct `export-drumgizmo` CLI both
recompute these identities immediately before export. `campaign.json` also
freezes the SHA-256 of the exact session note/channel/controller grid, so a
same-size session edited after campaign creation cannot be recalibrated into a
different kit by accident. A partial library, a
changed raw/composite WAV, a stale session/plan, or a changed approved SD3
preset therefore blocks XML generation instead of producing a structurally
valid but musically incomplete kit.

The sampler always requires `--confirm-capture`, writes only missing raw take
names, and records the source/licensing declaration in its neutral library.
It also enforces the session's explicit `cooldown_ms` between newly captured
takes, so dense VST or module sessions do not depend on an undocumented
one-off delay. Already-complete takes remain skipped and do not add a delay.

The two layered snare centers are a separate fidelity gate for DrumGizmo.
After the 939 individual takes and their strict 48 kHz/stereo quality report,
`capture-composites` triggers each approved SD3 layer as one simultaneous MIDI
chord: notes 37+100+101 for the Deftones center and 42+103 for the Sleep Token
center. It records 42 additional coherent takes (seven velocities, three
round robins, two centers). This direct capture is authoritative for the
DrumGizmo center attacks; summing separately recorded WAV files is only an
offline diagnostic fallback because independent capture-onset jitter can
misalign their transients. A dedicated `composite-quality.json` must accept
all 42 files before the Control Center enables export.

If only non-audio metadata in the MegaKit YAML changes after capture (for
example the approval status or a new renderer capability), re-attest the
existing composites with `drum-sampler audit-composites`. This command opens
no MIDI or audio device: it rebuilds the expected composite grid from the
current plan, re-measures every WAV and writes a new bound quality report. A
changed chord definition, missing file, duplicate round robin or altered WAV
still fails. `capture-composites` remains the only command that sends MIDI and
records audio.

After export, **Validate exported DrumGizmo files** parses every XML document,
checks every MIDI/instrument/WAV-channel reference and writes a SHA-256 manifest
for the complete self-contained kit. This internal pass does not require a
DrumGizmo installation. **Probe installed DrumGizmo host** is deliberately a
separate gate: it records the executable version/backend when the target host
is available and does not turn a missing Windows executable into a false
failure of the generated kit.

For the r5 package this external gate is complete. Run
`scripts/smoke-drumgizmo-wsl.ps1`: it invokes `dgvalidator --pedantic`, then
loads the full kit in DrumGizmo with streaming enabled, synthetic `test` input,
`dummy` output and a bounded 48,000-frame run. It then renders the same crash
twice through the `midifile`/`wavfile` engines, with Poly Aftertouch 0 and 127,
and requires at least 12 dB of measured tail attenuation. The r5 proof measured
23.69 dB. The resulting JSON proves clean load, choke and exit without opening
MIDI, ALSA or JACK hardware.

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
