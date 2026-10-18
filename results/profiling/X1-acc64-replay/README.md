# X1 isolated kernel investigation

Artifact: `57fc3bcfd1ec6a017f495372f05c99fffa29962319898cd43f168aaf61314dfe`.
Verified 20 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 35609887 | 1 | performance |
| baseline/node:58 | 9013968 | 1 | performance |
| zeros/node:4 | 35487372 | 1 | performance |
| zeros/node:58 | 9013837 | 1 | performance |
| maximum/node:4 | 35464499 | 1 | performance |
| maximum/node:58 | 9014592 | 1 | performance |
| zero_point/node:4 | 35536886 | 1 | performance |
| zero_point/node:58 | 9017559 | 1 | performance |
| alternating/node:4 | 35525559 | 1 | performance |
| alternating/node:58 | 9013647 | 1 | performance |
| ramp/node:4 | 35562252 | 1 | performance |
| ramp/node:58 | 9012028 | 1 | performance |
| random_42/node:4 | 35610250 | 1 | performance |
| random_42/node:58 | 9012825 | 1 | performance |
| random_deadbeef/node:4 | 35610089 | 1 | performance |
| random_deadbeef/node:58 | 9013257 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
