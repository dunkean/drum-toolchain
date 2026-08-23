#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir="$repo_root/build-linux-firmware"

mkdir -p "$output_dir"
cd "$repo_root"

: "${CXX:=g++}"
"$CXX" -std=c++17 \
  -I firmware/ddrum4-midi-bridge/include \
  -I firmware/ddrum4-midi-bridge/test/support \
  firmware/ddrum4-midi-bridge/src/DdrumBridge.cpp \
  firmware/ddrum4-midi-bridge/src/MidiDinAdapter.cpp \
  firmware/ddrum4-midi-bridge/native_tests/bridge_core_msvc.cpp \
  -o "$output_dir/bridge_core_tests"

"$output_dir/bridge_core_tests"
