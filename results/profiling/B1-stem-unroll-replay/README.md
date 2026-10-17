# B1 isolated kernel investigation

Artifact: `91e6581c75dd18aa06d8bc8eef38f2a595ebe854dc3b0f33f455ba9457778bd2`.
Verified 10 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:1 | 126483738 | 1 | performance |
| zeros/node:1 | 126481048 | 1 | performance |
| maximum/node:1 | 126468391 | 1 | performance |
| zero_point/node:1 | 126430425 | 1 | performance |
| alternating/node:1 | 126468167 | 1 | performance |
| ramp/node:1 | 126494161 | 1 | performance |
| random_42/node:1 | 126484196 | 1 | performance |
| random_deadbeef/node:1 | 126483696 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
