#!/usr/bin/env bash
# Keep the Windows SSH -> wsl.exe session open until both children complete.
# Detached Linux processes alone did not survive that session closing on the
# initial Windows host. A run without completion evidence is interrupted.
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
cd "$project"
label=${CVW_RUN_LABEL:-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p build/cvw/runs
python3 tools/cvw/run.py B0 --output "build/cvw/runs/B0-$label" > "build/cvw/runs/B0-$label-launch.log" 2>&1 &
b0_pid=$!
python3 tools/cvw/run.py B1 --output "build/cvw/runs/B1-$label" > "build/cvw/runs/B1-$label-launch.log" 2>&1 &
b1_pid=$!
echo "B0 runner: $b0_pid; B1 runner: $b1_pid; run label: $label"
status=0
wait "$b0_pid" || status=1
wait "$b1_pid" || status=1
exit "$status"
