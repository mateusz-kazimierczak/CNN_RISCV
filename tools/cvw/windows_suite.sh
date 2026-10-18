#!/usr/bin/env bash
# The Windows-owned wsl.exe process remains alive until the suite exits.
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
cd "$project"
label=${1:?A fresh run label is required}
suite=${2:-baseline}
[[ $label =~ ^[A-Za-z0-9_.-]+$ ]] || exit 2
[[ $suite == baseline || $suite == custom || $suite == postinc ]] || exit 2
mkdir -p build/cvw/runs
exec > "build/cvw/runs/windows-$label.log" 2>&1
export CVW_RUN_LABEL="$label"
if [[ $suite == postinc ]]; then
  bash tools/cvw/run_postinc_suite.sh
elif [[ $suite == custom ]]; then
  bash tools/cvw/run_custom_suite.sh
else
  bash tools/cvw/run_suite.sh
fi
