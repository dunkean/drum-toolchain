# Drum Control Center

The Control Center is the offline workstation entry point for rig-project
work. It never opens MIDI ports or sends MIDI unless the operator explicitly
launches a separate hardware-capable application. It delegates validation,
compilation, and reports to the installed `drum-toolchain` command.

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
5. Run **Quality review**, select the compiled DrumGizmo note map, then export
   and verify the complete DrumGizmo kit.

The status line is file-backed: it counts expected and recorded raw takes and
reports whether the library, quality report, and DrumGizmo directory exist. It
never treats a recorded file as an artistically approved sound. The separate
**Rig, DDrum4, and applications** tab retains the simulator, compiler,
DDrum4 matrix, and explicit launch controls for DDTi, ddrum4UI, Converter, and
an SD3/DAW or DrumGizmo host.

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
simulator panel after selecting a rig project.

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
