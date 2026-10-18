#!/usr/bin/env bash
# Windows owns this process through preflight and the full X3 inference run.
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
python3 tools/cvw/prepare_full_custom.py X3
python3 tools/cvw/smoke.py --custom X3 --wally build/cvw/full-xpostinc --output "build/cvw/runs/X3-$label-smoke" > "build/cvw/runs/X3-$label-smoke.log" 2>&1
python3 tools/cvw/run.py X3 --contract tools/cvw/postinc_workloads.json --wally build/cvw/full-xpostinc --inputs build/cvw/postinc-inputs --output "build/cvw/runs/X3-$label" > "build/cvw/runs/X3-$label-launch.log" 2>&1
