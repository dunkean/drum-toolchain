# Drum Control Center

The Control Center is a small launcher for offline rig-project work.  It never
opens MIDI ports or sends MIDI.  It delegates validation, compilation, and
reports to the installed `drum-toolchain` command.

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
