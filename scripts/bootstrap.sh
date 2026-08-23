#!/usr/bin/env sh
# Linux/WSL prerequisite checker and opt-in installer for the portable stack.
set -u

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install=false

if [ "${1:-}" = "--install" ]; then
  install=true
elif [ "$#" -ne 0 ]; then
  printf '%s\n' "usage: scripts/bootstrap.sh [--install]" >&2
  exit 2
fi

packages='python3.12-venv build-essential cmake ninja-build pkg-config libx11-dev libxext-dev libxinerama-dev libxrandr-dev libxcursor-dev libasound2-dev libfreetype-dev libfontconfig1-dev libgl1-mesa-dev libportaudio2 jackd2 a2jmidid alsa-utils drumgizmo'

if "$install"; then
  if ! command -v sudo >/dev/null 2>&1; then
    printf '%s\n' "--install requires sudo and an apt-based Linux distribution." >&2
    exit 2
  fi
  if ! sudo -n true >/dev/null 2>&1; then
    printf '%s\n' "--install needs an interactive sudo session; run it from a terminal with sudo access." >&2
    exit 2
  fi
  sudo apt-get update
  # JACK's real-time scheduling policy is deliberately left to the local host
  # configuration. This project never changes it automatically.
  sudo apt-get install -y $packages
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

check_command "CMake" "cmake"
check_command "Ninja" "ninja"
check_command "pkg-config" "pkg-config"
check_command "DrumGizmo" "drumgizmo"
check_command "JACK port inspector" "jack_lsp"
check_command "JACK connector" "jack_connect"
check_command "ALSA-to-JACK bridge" "a2jmidid"
check_command "ALSA port inspector" "aconnect"

if "$install" && [ ! -x "$repo_root/.venv/bin/python" ]; then
  python3.12 -m venv "$repo_root/.venv"
fi

if "$install" && [ -x "$repo_root/.venv/bin/python" ]; then
  "$repo_root/.venv/bin/python" -m pip install --disable-pip-version-check platformio
elif "$install"; then
  printf '%s\n' "PlatformIO: Python 3.12 could not create the project virtual environment." >&2
  status=1
fi

if [ -x "$repo_root/.venv/bin/pio" ]; then
  "$repo_root/.venv/bin/pio" --version
else
  printf '%s\n' "PlatformIO: missing; run scripts/bootstrap.sh --install." >&2
  status=1
fi

if [ ! -e /dev/snd/seq ]; then
  printf '%s\n' "ALSA sequencer: unavailable; WSL needs USB MIDI and ALSA sequencer exposure for live ports." >&2
  status=1
else
  printf '%s\n' "ALSA sequencer: available"
fi

if [ -e /dev/snd/controlC0 ] && [ ! -r /dev/snd/controlC0 ]; then
  printf '%s\n' "ALSA device access: unavailable; add $USER to the audio group and restart the WSL distribution." >&2
  status=1
fi

if [ -r /proc/config.gz ] && zcat /proc/config.gz 2>/dev/null | grep -q '^# CONFIG_SND_SEQUENCER is not set$'; then
  printf '%s\n' "WSL kernel: CONFIG_SND_SEQUENCER is disabled; RtMidi/JACK-MIDI live routing needs a custom WSL kernel or native Linux." >&2
  status=1
fi

exit "$status"
