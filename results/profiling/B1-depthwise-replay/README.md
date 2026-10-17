# B1 isolated kernel investigation

Artifact: `41baf1a513cb3e11287f1e4414bd96e1ce2659f53814303f0b4e31d344e40e6a`.
Verified 18 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:8 | 56806696 | 1 | performance |
| baseline/node:15 | 42275283 | 1 | performance |
| zeros/node:8 | 56791131 | 1 | performance |
| zeros/node:15 | 42273676 | 1 | performance |
| maximum/node:8 | 56801592 | 1 | performance |
| maximum/node:15 | 42272862 | 1 | performance |
| zero_point/node:8 | 56803957 | 1 | performance |
| zero_point/node:15 | 42272049 | 1 | performance |
| alternating/node:8 | 56793616 | 1 | performance |
| alternating/node:15 | 42272899 | 1 | performance |
| ramp/node:8 | 56806161 | 1 | performance |
| ramp/node:15 | 42273070 | 1 | performance |
| random_42/node:8 | 56806739 | 1 | performance |
| random_42/node:15 | 42275306 | 1 | performance |
| random_deadbeef/node:8 | 56806543 | 1 | performance |
| random_deadbeef/node:15 | 42275276 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
