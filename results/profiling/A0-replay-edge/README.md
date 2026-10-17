# A0 isolated kernel investigation

Artifact: `53cfe732bf2bfb93851072cc0367d452522d81f34343d0704d57fda5176ed0d6`.
Verified 8 fixtures per build (rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:10 | 8126007 | 1 | performance |
| baseline/node:60 | 2 | 1 | performance |
| baseline/node:62 | 703879 | 1 | performance |
| zero_point/node:10 | 8060969 | 1 | performance |
| zero_point/node:60 | 2 | 1 | performance |
| zero_point/node:62 | 225613 | 1 | diagnostic error |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
