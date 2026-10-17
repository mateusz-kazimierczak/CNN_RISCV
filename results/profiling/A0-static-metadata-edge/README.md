# A0 isolated kernel investigation

Artifact: `2c8239b1267e8fd90f45bb53b7862b93516cee2b656cf920bb1e9bf3935f855c`.
Verified 8 fixtures per build (rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:10 | 8125736 | 1 | performance |
| baseline/node:60 | 2 | 1 | performance |
| baseline/node:62 | 703878 | 1 | performance |
| zero_point/node:10 | 8060698 | 1 | performance |
| zero_point/node:60 | 2 | 1 | performance |
| zero_point/node:62 | 225612 | 1 | diagnostic error |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
