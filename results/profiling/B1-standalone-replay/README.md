# B1 isolated kernel investigation

Artifact: `4d095335d8b279deffaba4320ae6495628fbbe1de13cfa730487e81bc9f1e745`.
Verified 90 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:0 | 112909 | 1 | performance |
| baseline/node:1 | 90810140 | 1 | performance |
| baseline/node:4 | 118477195 | 1 | performance |
| baseline/node:8 | 54548776 | 1 | performance |
| baseline/node:10 | 4211880 | 1 | performance |
| baseline/node:15 | 41334483 | 1 | performance |
| baseline/node:58 | 69949393 | 1 | performance |
| baseline/node:59 | 272643 | 1 | performance |
| baseline/node:60 | 2 | 1 | performance |
| baseline/node:61 | 6931437 | 1 | performance |
| baseline/node:62 | 298769 | 1 | performance |
| zeros/node:0 | 112909 | 1 | performance |
| zeros/node:1 | 90807450 | 1 | performance |
| zeros/node:4 | 118452808 | 1 | performance |
| zeros/node:8 | 54533211 | 1 | performance |
| zeros/node:10 | 4209832 | 1 | performance |
| zeros/node:15 | 41332876 | 1 | performance |
| zeros/node:58 | 69949363 | 1 | performance |
| zeros/node:59 | 272649 | 1 | performance |
| zeros/node:60 | 2 | 1 | performance |
| zeros/node:61 | 6931441 | 1 | performance |
| zeros/node:62 | 290933 | 1 | performance |
| maximum/node:0 | 112909 | 1 | performance |
| maximum/node:1 | 90794793 | 1 | performance |
| maximum/node:4 | 118440935 | 1 | performance |
| maximum/node:8 | 54543672 | 1 | performance |
| maximum/node:10 | 4212368 | 1 | performance |
| maximum/node:15 | 41332062 | 1 | performance |
| maximum/node:58 | 69949361 | 1 | performance |
| maximum/node:59 | 272650 | 1 | performance |
| maximum/node:60 | 2 | 1 | performance |
| maximum/node:61 | 6931451 | 1 | performance |
| maximum/node:62 | 290384 | 1 | performance |
| zero_point/node:0 | 112909 | 1 | performance |
| zero_point/node:1 | 90756827 | 1 | performance |
| zero_point/node:4 | 118428054 | 1 | performance |
| zero_point/node:8 | 54546037 | 1 | performance |
| zero_point/node:10 | 4146842 | 1 | performance |
| zero_point/node:15 | 41331249 | 1 | performance |
| zero_point/node:58 | 69949388 | 1 | performance |
| zero_point/node:59 | 272652 | 1 | performance |
| zero_point/node:60 | 2 | 1 | performance |
| zero_point/node:61 | 6931492 | 1 | performance |
| zero_point/node:62 | 130450 | 1 | diagnostic error |
| alternating/node:0 | 112909 | 1 | performance |
| alternating/node:1 | 90794569 | 1 | performance |
| alternating/node:4 | 118428282 | 1 | performance |
| alternating/node:8 | 54535696 | 1 | performance |
| alternating/node:10 | 4217182 | 1 | performance |
| alternating/node:15 | 41332099 | 1 | performance |
| alternating/node:58 | 69949360 | 1 | performance |
| alternating/node:59 | 272648 | 1 | performance |
| alternating/node:60 | 2 | 1 | performance |
| alternating/node:61 | 6931451 | 1 | performance |
| alternating/node:62 | 292524 | 1 | performance |
| ramp/node:0 | 112909 | 1 | performance |
| ramp/node:1 | 90820563 | 1 | performance |
| ramp/node:4 | 118459169 | 1 | performance |
| ramp/node:8 | 54548241 | 1 | performance |
| ramp/node:10 | 4244872 | 1 | performance |
| ramp/node:15 | 41332270 | 1 | performance |
| ramp/node:58 | 69949388 | 1 | performance |
| ramp/node:59 | 272647 | 1 | performance |
| ramp/node:60 | 2 | 1 | performance |
| ramp/node:61 | 6931474 | 1 | performance |
| ramp/node:62 | 300783 | 1 | performance |
| random_42/node:0 | 112909 | 1 | performance |
| random_42/node:1 | 90810598 | 1 | performance |
| random_42/node:4 | 118477191 | 1 | performance |
| random_42/node:8 | 54548819 | 1 | performance |
| random_42/node:10 | 4212150 | 1 | performance |
| random_42/node:15 | 41334506 | 1 | performance |
| random_42/node:58 | 69949402 | 1 | performance |
| random_42/node:59 | 272645 | 1 | performance |
| random_42/node:60 | 2 | 1 | performance |
| random_42/node:61 | 6931447 | 1 | performance |
| random_42/node:62 | 299263 | 1 | performance |
| random_deadbeef/node:0 | 112909 | 1 | performance |
| random_deadbeef/node:1 | 90810098 | 1 | performance |
| random_deadbeef/node:4 | 118477311 | 1 | performance |
| random_deadbeef/node:8 | 54548623 | 1 | performance |
| random_deadbeef/node:10 | 4212114 | 1 | performance |
| random_deadbeef/node:15 | 41334476 | 1 | performance |
| random_deadbeef/node:58 | 69949416 | 1 | performance |
| random_deadbeef/node:59 | 272644 | 1 | performance |
| random_deadbeef/node:60 | 2 | 1 | performance |
| random_deadbeef/node:61 | 6931443 | 1 | performance |
| random_deadbeef/node:62 | 297674 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
