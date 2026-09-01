# Drum Control Center

The Control Center is the workstation entry point for rig-project work. Its
editors, simulator, readiness inspector, compilation and reports are offline.
Hardware validation is available only through dedicated actions that disclose
their I/O, use bounded helper processes and require explicit operator
confirmation before capture or transmission.

## Start a new SD3 kit capture

Use `drum-control-center-gui` and open **SD3 capture campaign**. This is the
normal starting point when capturing a new SD3 MegaKit:

1. Select a campaign root and provide an English campaign ID, the exact SD3
   preset, MIDI input, audio input, and channel layout.
2. Load the editable starter grid or enter every kit-specific articulation.
   Confirm its MIDI notes in SD3 before continuing; a starter row is not a
   measured mapping.
   For the current 8 MB Metalcore/electronic V1, **Add V1
   Metalcore/electronic additions** appends the approved percussion and
   electronic source rows. Its exact notes and DDrum4 destinations are in
   [`docs/SD3_MEGAKIT_V1_CAPTURE_LIST.md`](../../docs/SD3_MEGAKIT_V1_CAPTURE_LIST.md).
3. Click **Create new campaign and capture session**. This creates a new
   `campaign.json` and standard `capture-session.json`, but does not open MIDI
   or audio devices.
4. Load the declared SD3 preset and check gain/routing, then choose
   **Capture pending takes**. The app asks for a final confirmation before it
   sends MIDI or records audio, and keeps the UI responsive while the sampler
   runs.
5. Run **Quality review**, then **Capture simultaneous layered centers** for
   plans which declare them. Select the compiled DrumGizmo note map only after
   both quality reports pass, then export and verify the complete DrumGizmo
   kit. Internal XML/WAV/hash validation is separate from the optional probe
   of an installed DrumGizmo host.

The status line is file-backed: it counts expected raw and composite takes,
checks that the quality report fingerprints the current immutable library,
checks the exact capture-session hash frozen by the campaign, and requires
every expected WAV to pass before export. It never treats a
technically valid recording as an artistically approved sound. The separate
**Rig, DDrum4, and applications** tab retains the simulator, compiler,
DDrum4 matrix, and explicit launch controls for DDTi, ddrum4UI, Converter, and
an SD3/DAW or DrumGizmo host.

The **Validation & deployment** page also provides **Capture next physical
trace (receive-only)…** for post-configuration hardware verification. It opens
only the exact input selected by the operator for a bounded window, never a
MIDI output. Existing rejected traces are archived before replacement and the
campaign review is refreshed when the subprocess exits.

The same page groups the 30 DDrum4 Scene/Palette panel proofs behind
**Capture all Scene/Palette controls (receive-only)…**. One bounded recording
is accepted only when every expected command occurs once, in the displayed
order; publication of the 30 isolated traces is atomic. **Probe isolated
DDrum4 echo/soft-through…** is intentionally different: after two topology
confirmations it sends a bounded 300-message diagnostic and writes a local
report. It must be used only with Arduino OUT physically disconnected from
DDrum4 IN, as shown in the dialog.

`promote-configured` closes the first-flash hi-hat gate from the eDRUMin
snapshot and the prescribed normalized contract, without pads. Later traces
must match the prescribed channel/CC exactly and refine pedal calibration;
they never replace the source address. The generated project is explicitly
`validation_stage: post-flash-validation-pending`: it may build and flash the
reviewed bridge, but the one-click live launcher refuses it until pad traces
produce a later `hardware-verified` promotion.

Pressure/choke verification uses a separate proof gate. Each isolated trace must
contain one target Note On followed by Poly Aftertouch on the same channel and
note, with no other active hit. That trace proves only the source-module MIDI
behavior. The operator must then explicitly confirm the intended DDrum4 and
SD3 active-hit renderer targets; the tool records them as `user-confirmed`,
never as audio-measured, and leaves DrumGizmo choke unsupported.

## Complete-chain simulator

The integrated simulator follows one declared raw pad event through the source
profile, logical Scene/VP state, Arduino DDrum4 return, SD3 MegaKit, and
DrumGizmo kit. It models routing only: it never opens MIDI, loads the SD3 or
DrumGizmo VST, produces audio, or contacts hardware.

`profiles/projects/complete-chain-simulator.yaml` is an explicitly synthetic
demo profile. Its MIDI addresses are suitable for simulation tests only; do
not copy them to a module.

```powershell
drum-control-center simulate profiles/projects/complete-chain-simulator.yaml `
  --source ddrum4 --note 85 --velocity 106 --scene dnb
```

Use `--state vp1_snare=1` (repeatable) to test virtual-palette variants, and
`--json` for a complete machine-readable trace. The GUI contains the same
simulator panel after selecting a rig project. Positional Note ranges are not
collapsed in this view: the Snare2 row exposes one direct `P1`…`P8` button per
raw NOTE P position, and the trace shows the resulting SD3 CC16 plus the
quantized DDrum4 Center/Mid/Edge note.

## DDrum4 offline matrix

Choose a local kit matrix manifest (for example
`profiles/ddrum4-kit-matrix.example.yaml`) and optional ddrum4-bank-builder
reports. The GUI displays ten Sound slots, their declared WAV layers, encoded
block count, and a separately reported `MEM.LEFT` delta. `unknown` means no
module measurement exists; it is never estimated. WAV audition is an explicit
local default-player action. The matrix never opens MIDI, calls ddrum4edit, or
uploads anything.

```powershell
python -m pip install -e 'apps/control-center[gui]'
drum-control-center validate profiles/projects/greg-hybrid-mvp.yaml --dry-run
drum-control-center compile profiles/projects/greg-hybrid-mvp.yaml --output build/rig
drum-control-center launch-converter --converter C:/path/to/ddrum4_converter.exe --runtime-profile build/rig/runtime-profile.yaml
```

`launch-ddti` and `launch-ddrum4ui` are explicit launch actions.  The latter
requires the path to `ddrum4UI`; converter launch requires the compiled
`runtime-profile.yaml` and passes it via `DDRUM4_RUNTIME_PROFILE`. The Control Center does not discover devices,
automate either application, or duplicate their MIDI interfaces.
