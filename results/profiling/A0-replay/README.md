# A0 isolated kernel investigation

Artifact: `bbf096c4f8bfaebd1d2db0a827ebf76110247a06504eb3445d3562e48181f599`.
Verified 8 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:1 | 281448170 | 1 | performance |
| baseline/node:4 | 398850865 | 1 | performance |
| baseline/node:8 | 158487356 | 1 | performance |
| baseline/node:15 | 136114950 | 1 | performance |
| baseline/node:58 | 249752376 | 1 | performance |
| baseline/node:61 | 15415710 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
