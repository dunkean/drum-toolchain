#!/usr/bin/env sh
# Explicit Linux DrumGizmo session wrapper. MIDI is routed only by Converter.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -n "${PYTHON:-}" ]; then
  python_bin=$PYTHON
elif [ -x "$repo_root/.venv/bin/python" ]; then
  python_bin="$repo_root/.venv/bin/python"
else
  python_bin=python3
fi
exec "$python_bin" -m midi_lab.live_session start "$@"
