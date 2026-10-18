# Xpostinc on CV-Wally

**PASS**: 145 self-checking program runs on six real Wally SoC configurations.

- 12,672 identical Spike/RTL vectors; 12,683 memory retirements per vector run.
- 35 fault fixtures with normal/stalled execution, unchanged registers and guarded RAM.
- Dual-result forwarding, dependent loads/stores, aliases, x0, and branch/trap flushes.
- Sv39 TLB miss success, page faults, and alignment priority over unmapped pages.
- Mandatory custom alignment with Zicclsm enabled; ordinary misaligned accesses still work.
- Independent enables, RV32 rejection, base/M/C compatibility and earlier custom regressions.
- Original verified X3 compiler ELF: 12 complete fixtures, 4,039,184 output bytes and guards compared.
- Replay retirements: 3,494,912 post-increment loads, 1,507,840 stores; zero unexpected traps.

[Detailed evidence](verification.json), [authenticated summary](summary.json), [per-program counts](cases.csv).

Reproduce with `gmake cvw-xpostinc-checkpoint`; see [implementation and setup](../../../docs/cvw-xpostinc.md).

Cycles in cases.csv include setup, console and self-checks. Full-inference cycles and physical timing/area are unmeasured. Source, simulator, ELF and log hashes are authenticated by `python3 tools/cvw/xpostinc/report.py`; retain the ignored build evidence.
