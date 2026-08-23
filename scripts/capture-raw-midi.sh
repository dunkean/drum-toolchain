#!/usr/bin/env sh
# Bounded, receive-only raw MIDI capture for Linux/WSL diagnosis.
set -eu

usage() {
  printf '%s\n' "usage: scripts/capture-raw-midi.sh --port <ALSA raw MIDI port> --seconds <positive integer> --output <file>" >&2
  exit 2
}

port=''
seconds=''
output=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --port) port=${2:-}; shift 2 ;;
    --seconds) seconds=${2:-}; shift 2 ;;
    --output) output=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done

[ -n "$port" ] && [ -n "$output" ] || usage
case "$seconds" in
  *[!0-9]*|'') usage ;;
esac
[ "$seconds" -gt 0 ] || usage

command -v amidi >/dev/null 2>&1 || {
  printf '%s\n' "amidi is required; install alsa-utils." >&2
  exit 2
}

if [ -e /dev/snd/controlC0 ] && [ ! -r /dev/snd/controlC0 ]; then
  printf '%s\n' "ALSA access denied. Add $USER to the audio group, then restart WSL before retrying." >&2
  exit 2
fi

if [ -e "$output" ]; then
  printf '%s\n' "refusing to overwrite existing capture: $output" >&2
  exit 2
fi

set +e
timeout "$seconds" amidi -p "$port" -d >"$output"
result=$?
set -e
if [ "$result" -ne 0 ] && [ "$result" -ne 124 ]; then
  exit "$result"
fi

printf 'captured %s bytes from %s to %s\n' "$(wc -c <"$output")" "$port" "$output"
