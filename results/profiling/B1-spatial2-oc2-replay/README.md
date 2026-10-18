# B1 isolated kernel investigation

Artifact: `72dc4663749b936f3964d7e11f42f439e479a487046e0709281c388ab5ea6c00`.
Verified 58 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:1 | 78960244 | 1 | performance |
| baseline/node:4 | 94108830 | 1 | performance |
| baseline/node:8 | 38351741 | 1 | performance |
| baseline/node:15 | 35403916 | 1 | performance |
| baseline/node:58 | 64647249 | 1 | performance |
| baseline/node:61 | 6931437 | 1 | performance |
| baseline/node:62 | 298769 | 1 | performance |
| zeros/node:1 | 78893371 | 1 | performance |
| zeros/node:4 | 93986315 | 1 | performance |
| zeros/node:8 | 38342613 | 1 | performance |
| zeros/node:15 | 35409870 | 1 | performance |
| zeros/node:58 | 64647118 | 1 | performance |
| zeros/node:61 | 6931441 | 1 | performance |
| zeros/node:62 | 290933 | 1 | performance |
| maximum/node:1 | 78918346 | 1 | performance |
| maximum/node:4 | 93963442 | 1 | performance |
| maximum/node:8 | 38342583 | 1 | performance |
| maximum/node:15 | 35415671 | 1 | performance |
| maximum/node:58 | 64647873 | 1 | performance |
| maximum/node:61 | 6931451 | 1 | performance |
| maximum/node:62 | 290384 | 1 | performance |
| zero_point/node:1 | 78842413 | 1 | performance |
| zero_point/node:4 | 94035829 | 1 | performance |
| zero_point/node:8 | 38334960 | 1 | performance |
| zero_point/node:15 | 35408110 | 1 | performance |
| zero_point/node:58 | 64650840 | 1 | performance |
| zero_point/node:61 | 6931492 | 1 | performance |
| zero_point/node:62 | 130450 | 1 | diagnostic error |
| alternating/node:1 | 78955531 | 1 | performance |
| alternating/node:4 | 94024502 | 1 | performance |
| alternating/node:8 | 38354893 | 1 | performance |
| alternating/node:15 | 35412508 | 1 | performance |
| alternating/node:58 | 64646928 | 1 | performance |
| alternating/node:61 | 6931451 | 1 | performance |
| alternating/node:62 | 292524 | 1 | performance |
| ramp/node:1 | 78952971 | 1 | performance |
| ramp/node:4 | 94061195 | 1 | performance |
| ramp/node:8 | 38351451 | 1 | performance |
| ramp/node:15 | 35407457 | 1 | performance |
| ramp/node:58 | 64645309 | 1 | performance |
| ramp/node:61 | 6931474 | 1 | performance |
| ramp/node:62 | 300783 | 1 | performance |
| random_42/node:1 | 78960649 | 1 | performance |
| random_42/node:4 | 94109193 | 1 | performance |
| random_42/node:8 | 38350997 | 1 | performance |
| random_42/node:15 | 35404234 | 1 | performance |
| random_42/node:58 | 64646106 | 1 | performance |
| random_42/node:61 | 6931447 | 1 | performance |
| random_42/node:62 | 299263 | 1 | performance |
| random_deadbeef/node:1 | 78960461 | 1 | performance |
| random_deadbeef/node:4 | 94109032 | 1 | performance |
| random_deadbeef/node:8 | 38350583 | 1 | performance |
| random_deadbeef/node:15 | 35403839 | 1 | performance |
| random_deadbeef/node:58 | 64646538 | 1 | performance |
| random_deadbeef/node:61 | 6931443 | 1 | performance |
| random_deadbeef/node:62 | 297674 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
