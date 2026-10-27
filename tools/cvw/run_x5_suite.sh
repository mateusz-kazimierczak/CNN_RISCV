#!/usr/bin/env bash
# Windows owns this process through preflight and the full X5 inference on the existing X4 core run.
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
hardware_sha=$(python3 tools/cvw/reuse_hardware.py --output "build/cvw/runs/X5-$label-smoke")
python3 tools/cvw/run.py X5 --contract tools/cvw/x5_workloads.json --wally build/cvw/full-xdwmac8 --inputs build/cvw/x5-inputs --expected-simulator-sha256 "$hardware_sha" --output "build/cvw/runs/X5-$label" > "build/cvw/runs/X5-$label-launch.log" 2>&1
