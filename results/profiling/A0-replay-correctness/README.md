# A0 isolated kernel investigation

Artifact: `715ae2b4d826576f82af521e6ec435ea275a805a939f40ec5af7ed91f8fd0d2c`.
Verified 74 fixtures per build (native, sanitized).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
