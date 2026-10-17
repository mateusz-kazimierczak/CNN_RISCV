# B1 isolated kernel investigation

Artifact: `a316899557b3ed1864c701cdcb45b8f348b4e8c23469241578a079b26438b2da`.
Verified 18 fixtures per build (rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 132024717 | 1 | performance |
| baseline/node:58 | 77303069 | 1 | performance |
| zeros/node:4 | 132000330 | 1 | performance |
| zeros/node:58 | 77303039 | 1 | performance |
| maximum/node:4 | 131988457 | 1 | performance |
| maximum/node:58 | 77303037 | 1 | performance |
| zero_point/node:4 | 131975576 | 1 | performance |
| zero_point/node:58 | 77303064 | 1 | performance |
| alternating/node:4 | 131975804 | 1 | performance |
| alternating/node:58 | 77303036 | 1 | performance |
| ramp/node:4 | 132006691 | 1 | performance |
| ramp/node:58 | 77303064 | 1 | performance |
| random_42/node:4 | 132024713 | 1 | performance |
| random_42/node:58 | 77303078 | 1 | performance |
| random_deadbeef/node:4 | 132024833 | 1 | performance |
| random_deadbeef/node:58 | 77303092 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
