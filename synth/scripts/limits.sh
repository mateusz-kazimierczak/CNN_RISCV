# Per-process limits for this job and its children on the CentOS Linux host.
# Fail closed if any requested limit cannot be established.
ulimit -c 0            # no core dumps
ulimit -t 14400        # four CPU hours per process
ulimit -v 16777216     # 16 GiB virtual address space per process (KiB)
ulimit -f 2097152      # file blocks: at most 2 GiB/file (shell units may be 512B)
# Wall time is bounded separately by timeout; no unbounded license wait/retry.
