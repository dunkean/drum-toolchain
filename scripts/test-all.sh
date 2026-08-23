#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_bin=${PYTHON:-python3}
venv_root="$repo_root/.venv"

if [ ! -x "$venv_root/bin/python" ]; then
  "$python_bin" -m venv "$venv_root"
fi

venv_python="$venv_root/bin/python"
python_version=$("$venv_python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$python_version" != "3.12" ]; then
  echo "scripts/test-all.sh requires Python 3.12; .venv uses $python_version. Remove .venv and rerun with PYTHON=<python3.12>." >&2
  exit 2
fi

"$venv_python" -m pip install --disable-pip-version-check -e "$repo_root" \
  -e "$repo_root/packages/drum-domain" \
  -e "$repo_root/apps/ddti" \
  -e "$repo_root/apps/control-center" \
  -e "$repo_root/apps/drum-sampler" \
  -e "$repo_root/apps/ddrum4-bank-builder" \
  -e "$repo_root/tools/midi-lab" \
  -e "$repo_root/tools/rig-compiler"

cd "$repo_root"
"$venv_python" -m unittest discover -s tests/python -p test_ddti.py -v
"$venv_python" -m unittest discover -s tests/python -p 'test_*.py' -v
"$venv_python" -m unittest discover -s apps/control-center/tests -p 'test_*.py' -v

"$repo_root/scripts/test-firmware-core.sh"
"$repo_root/scripts/test-modernizer-core.sh"
