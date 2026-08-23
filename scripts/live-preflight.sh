#!/usr/bin/env sh
# Read-only Linux/WSL readiness report. It never opens, writes, or routes MIDI.
set -u

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "${PYTHON:-}" ]; then
  python_bin=$PYTHON
elif [ -x "$repo_root/.venv/bin/python" ]; then
  python_bin="$repo_root/.venv/bin/python"
else
  python_bin=python3
fi
status=0

check_command() {
  label=$1
  command_name=$2
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '%s: %s\n' "$label" "$(command -v "$command_name")"
  else
    printf '%s: missing\n' "$label" >&2
    status=1
  fi
}

check_command "Python" "$python_bin"
check_command "DrumGizmo" "drumgizmo"
check_command "JACK port inspector" "jack_lsp"
check_command "JACK connector" "jack_connect"
check_command "ALSA-to-JACK bridge" "a2jmidid"
check_command "ALSA port inspector" "aconnect"

if "$python_bin" -c 'import mido, rtmidi; print("Python MIDI backend: available")'; then
  :
else
  printf '%s\n' "Python MIDI backend: unavailable" >&2
  status=1
fi

if "$python_bin" -m midi_lab.cli list --direction input; then
  :
else
  printf '%s\n' "MIDI input discovery failed. Under WSL, expose the USB MIDI device and ALSA sequencer before live validation." >&2
  status=1
fi

if "$python_bin" -m midi_lab.cli list --direction output; then
  :
else
  printf '%s\n' "MIDI output discovery failed. Under WSL, expose the USB MIDI device and ALSA sequencer before live validation." >&2
  status=1
fi

exit "$status"
