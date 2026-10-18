#!/usr/bin/env bash
# The Windows-owned wsl.exe process remains alive until the suite exits.
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
cd "$project"
label=${1:?A fresh run label is required}
[[ $label =~ ^[A-Za-z0-9_.-]+$ ]] || exit 2
mkdir -p build/cvw/runs
exec > "build/cvw/runs/windows-$label.log" 2>&1
export CVW_RUN_LABEL="$label"
bash tools/cvw/run_suite.sh
