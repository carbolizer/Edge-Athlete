#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  printf 'Linux x86_64 is required to generate this platform lock.\n' >&2
  exit 2
fi
python=${PYTHON:-python3.12}
python=$(command -v -- "$python")
if [[ $("$python" -c 'import struct,sys; print(f"{sys.version_info.major}.{sys.version_info.minor}:{struct.calcsize(chr(80)) * 8}")') != 3.12:64 ]]; then
  printf 'A 64-bit CPython 3.12 interpreter is required.\n' >&2
  exit 2
fi
(
  cd -- "$root"
  "$python" -m piptools compile \
    --allow-unsafe \
    --generate-hashes \
    --resolver=backtracking \
    --strip-extras \
    --upgrade \
    --output-file requirements-linux-x64.lock \
    requirements-build.txt
)
