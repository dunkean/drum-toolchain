#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

cd "$repo_root"

if command -v ninja >/dev/null 2>&1; then
  generator=Ninja
  build_suffix=ninja
else
  generator="Unix Makefiles"
  build_suffix=makefiles
fi
build_dir="$repo_root/build-linux-modernizer-tests-$build_suffix"

cmake -S . -B "$build_dir" -G "$generator" -DDDRUM4_BUILD_APP=OFF
cmake --build "$build_dir" --target ddrum4_core_tests ddrum4_rig_runtime_tests
ctest --test-dir "$build_dir" --output-on-failure
