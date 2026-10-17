# B1 isolated kernel investigation

Artifact: `68b9f32142d9f4cbc70f18a0cf184ce5947ce777eb53576d15b4ffea183e6623`.
Verified 18 fixtures per build (rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 124498315 | 1 | performance |
| baseline/node:58 | 70262993 | 1 | performance |
| zeros/node:4 | 124473928 | 1 | performance |
| zeros/node:58 | 70262963 | 1 | performance |
| maximum/node:4 | 124462055 | 1 | performance |
| maximum/node:58 | 70262961 | 1 | performance |
| zero_point/node:4 | 124449174 | 1 | performance |
| zero_point/node:58 | 70262988 | 1 | performance |
| alternating/node:4 | 124449402 | 1 | performance |
| alternating/node:58 | 70262960 | 1 | performance |
| ramp/node:4 | 124480289 | 1 | performance |
| ramp/node:58 | 70262988 | 1 | performance |
| random_42/node:4 | 124498311 | 1 | performance |
| random_42/node:58 | 70263002 | 1 | performance |
| random_deadbeef/node:4 | 124498431 | 1 | performance |
| random_deadbeef/node:58 | 70263016 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
