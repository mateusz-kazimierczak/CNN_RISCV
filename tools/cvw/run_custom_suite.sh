#!/usr/bin/env bash
# Keep the Windows-owned WSL process alive through builds, fixture gates and runs.
set -euo pipefail
cd "$(dirname "$0")/../.."
label=${CVW_RUN_LABEL:?A fresh run label is required}
mkdir -p build/cvw/runs
[[ ! -e build/cvw/runs/custom-$label.json ]] || exit 2
python3 - "$label" "$$" <<'PY'
import json,sys
from pathlib import Path
Path(f'build/cvw/runs/custom-{sys.argv[1]}.json').write_text(json.dumps({'status':'RUNNING','supervisor_pid':int(sys.argv[2])})+'\n')
PY
finish() {
  local code=$?
  python3 - "$label" "$code" <<'PY'
import json,sys
from pathlib import Path
p=Path(f'build/cvw/runs/custom-{sys.argv[1]}.json')
r=json.loads(p.read_text()); r.update(status='PASS' if sys.argv[2]=='0' else 'FAIL', exit_code=int(sys.argv[2]))
p.write_text(json.dumps(r)+'\n')
PY
}
trap finish EXIT
python3 tools/cvw/prepare_full_custom.py X1
python3 tools/cvw/prepare_full_custom.py X2
# Build and validate the exact full-inference testbench for both cores. Each
# fixture checks counts, coherent output, HTIF, and deliberate failure paths.
python3 tools/cvw/smoke.py --custom X1 --wally build/cvw/full-xqmac8 --output "build/cvw/runs/X1-$label-smoke" > "build/cvw/runs/X1-$label-smoke.log" 2>&1 &
x1_smoke=$!
python3 tools/cvw/smoke.py --custom X2 --wally build/cvw/full-xrequant --output "build/cvw/runs/X2-$label-smoke" > "build/cvw/runs/X2-$label-smoke.log" 2>&1 &
x2_smoke=$!
status=0
wait "$x1_smoke" || status=1
wait "$x2_smoke" || status=1
[[ $status == 0 ]] || exit 1
python3 tools/cvw/run.py X1 --contract tools/cvw/custom_workloads.json --wally build/cvw/full-xqmac8 --inputs build/cvw/custom-inputs --output "build/cvw/runs/X1-$label" > "build/cvw/runs/X1-$label-launch.log" 2>&1 &
x1=$!
python3 tools/cvw/run.py X2 --contract tools/cvw/custom_workloads.json --wally build/cvw/full-xrequant --inputs build/cvw/custom-inputs --output "build/cvw/runs/X2-$label" > "build/cvw/runs/X2-$label-launch.log" 2>&1 &
x2=$!
wait "$x1" || status=1
wait "$x2" || status=1
exit "$status"
