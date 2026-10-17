# B1 isolated kernel investigation

Artifact: `61b270c43f05feb94641217fb981a6e4b635f3963e4dced10a303c18151fd834`.
Verified 9 fixtures per build (rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:63 | 636 | 1 | performance |
| zeros/node:63 | 636 | 1 | performance |
| maximum/node:63 | 636 | 1 | performance |
| alternating/node:63 | 636 | 1 | performance |
| ramp/node:63 | 636 | 1 | performance |
| random_42/node:63 | 636 | 1 | performance |
| random_deadbeef/node:63 | 636 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
