# Sourced before any remote job write. No writes are performed by this guard.
synth_home=$(cd "$HOME" && pwd -P)
synth_job=$(pwd -P)
case "$synth_job" in
    "$synth_home"/*) ;;
    *) echo 'Refusing job directory outside the physical user home' >&2; exit 64 ;;
esac
# Payloads contain only regular files/directories. Reject existing links before
# writing logs, claiming a launch, or creating temporary/cache directories.
if [ -n "$(find . -type l -print -quit)" ]; then
    echo 'Refusing a job tree containing symlinks' >&2
    exit 64
fi
