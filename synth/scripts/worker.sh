#!/bin/sh
# POSIX sh + tcsh only: compatible with the observed CentOS 6 host.
set -eu
umask 077
cd "$(dirname "$0")/.."
. scripts/home_guard.sh
job=$(pwd -P)
root=$(dirname "$job")
# Stale locks are intentionally retained after a hard kill: inspect, don't guess.
if ! mkdir "$root/.active" 2>/dev/null; then
    printf '%s\n' 'Another job or stale lock exists; inspect .active/owner.' > logs/validation.log
    date -u '+%Y-%m-%dT%H:%M:%SZ' > status/ended_at
    echo 75 > status/exit_code
    echo FAILED > status/state.tmp
    mv status/state.tmp status/state
    exit 75
fi
printf '%s\n' "$job" > "$root/.active/owner"
finish() {
    code=$?
    trap - 0
    date -u '+%Y-%m-%dT%H:%M:%SZ' > status/ended_at
    printf '%s\n' "$code" > status/exit_code
    state=FAILED
    if [ "$code" -eq 0 ]; then state=SUCCEEDED; fi
    printf '%s\n' "$state" > status/state.tmp
    mv status/state.tmp status/state
    rm "$root/.active/owner"
    rmdir "$root/.active"
    exit "$code"
}
trap finish 0
trap 'exit 143' 15
trap 'exit 130' 2
mkdir -p tmp cache/alib
TMPDIR="$job/tmp"
TMP="$TMPDIR"
TEMP="$TMPDIR"
XDG_CACHE_HOME="$job/cache"
LC_ALL=C
LANG=C
OMP_NUM_THREADS=1
export TMPDIR TMP TEMP XDG_CACHE_HOME LC_ALL LANG OMP_NUM_THREADS
. scripts/limits.sh
ulimit -a > logs/resources.log
printf 'job=%s\ntmp=%s\ncache=%s\n' "$job" "$TMPDIR" "$XDG_CACHE_HOME" > status/storage_paths
hostname > status/hostname
printf '%s\n' "$$" > status/worker_pid
awk '{print $22}' "/proc/$$/stat" > status/process_start
printf '%s\n' "$job" > status/run_directory
date -u '+%Y-%m-%dT%H:%M:%SZ' > status/started_at
echo RUNNING > status/state.tmp
mv status/state.tmp status/state
sha256sum -c scripts/hashes.sha256 > logs/input_hashes.log 2>&1
# CentOS 6 timeout lacks -k. KILL at the wall limit terminates only the process
# group created by timeout, including this job's tool children. Worker stays out
# of that group so it can record failure and release its own lock.
timeout -s KILL 6h nice -n 10 /usr/bin/tcsh -f scripts/environment.csh > logs/dc.log 2>&1
# DC can exit 0 despite Tcl errors. Require the final sentinel and real reports.
test -s outputs/flow_complete
for file in area reference timing check_design check_timing qor library; do
    test -s "reports/$file.rpt"
done
test -s outputs/mapped.v
test -s outputs/mapped.sdc
test -s reports/metrics.tsv
test -s reports/cells.tsv
LC_ALL=C awk '/Total cell area:/ && $NF+0>0 {ok=1} END {exit !ok}' reports/area.rpt
LC_ALL=C grep -E 'slack[[:space:]]+\([A-Z]+\)[[:space:]]+-?[0-9]' reports/timing.rpt >/dev/null
if LC_ALL=C grep -E '(^|[[:space:]])Error:|^SYNTH_FATAL' logs/dc.log > logs/validation.log; then
    exit 65
fi
# Finite positive mapped area/count plus a constrained numerical path are required.
awk -F '\t' '
$1=="area" && $2+0>0 {a=1}
$1=="cell_count" && $2+0>0 {c=1}
$1=="arrival_ns" && $2 ~ /^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$/ {t=1}
$1=="slack_ns" && $2 ~ /^-?[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$/ {s=1}
END {exit !(a && c && t && s)}' reports/metrics.tsv
