#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  printf 'Linux x86_64 is required for this development build.\n' >&2
  exit 2
fi
python=${PYTHON:-python3.12}
if [[ $("$python" -c 'import struct,sys; print(f"{sys.version_info.major}.{sys.version_info.minor}:{struct.calcsize(chr(80)) * 8}")') != 3.12:64 ]]; then
  printf 'A 64-bit CPython 3.12 interpreter is required.\n' >&2
  exit 2
fi
"$python" -m pip install --require-virtualenv --require-hashes -r "$root/requirements-linux-x64.lock"
"$python" -m pip install --require-virtualenv --no-deps --no-build-isolation "$root"
"$python" -m pip check
"$python" -m unittest discover -s "$root/tests" -v
"$python" -m pip_audit --require-hashes -r "$root/requirements-linux-x64.lock"
(cd -- "$root" && "$python" -m PyInstaller --clean --noconfirm EdgeAthleteRackHelperDevelopment.spec)
"$python" -m cyclonedx_py requirements "$root/requirements-linux-x64.lock" \
  --output-file "$root/dist/EdgeAthleteRackHelperDevelopment.cdx.json"
