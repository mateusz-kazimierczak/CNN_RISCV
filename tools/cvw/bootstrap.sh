#!/usr/bin/env bash
# Minimal simulation dependencies only: no Linux image, FPGA or synthesis setup.
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
cd "$project"
jobs=${CVW_JOBS:-8}
wally_revision=712ee9719467e9e9987cebd55926ae8e01b08770
verilator_revision=24b2ac24c721fdad89bba75a492e02c6aa63f32e
mkdir -p .deps build/cvw

fetch_pinned() {
  local directory=$1 url=$2 revision=$3
  if [[ ! -d $directory/.git ]]; then
    git init "$directory"
    git -C "$directory" remote add origin "$url"
    git -C "$directory" fetch --depth 1 origin "$revision"
    git -C "$directory" checkout --detach FETCH_HEAD
  fi
  [[ $(git -C "$directory" rev-parse HEAD) == "$revision" ]] || {
    echo "Unexpected revision in $directory; preserve it and select a clean dependency path." >&2
    exit 1
  }
}

fetch_pinned .deps/cvw https://github.com/openhwfoundation/cvw.git "$wally_revision"
fetch_pinned .deps/verilator-src https://github.com/verilator/verilator.git "$verilator_revision"
if [[ ! -x .deps/verilator/bin/verilator ]]; then
  (
    cd .deps/verilator-src
    autoconf
    ./configure --prefix="$project/.deps/verilator"
    make -j"$jobs"
    make install
  ) > build/cvw/verilator-build.log 2>&1
fi
.deps/verilator/bin/verilator --version
python3 tools/cvw/prepare.py --source .deps/cvw --output build/cvw/wally
