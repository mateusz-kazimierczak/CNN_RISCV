# X1 isolated kernel investigation

Artifact: `9d6957fb06e9695ae22fad89d0effa9ca0d72ea5b40dfb2355213fdbfe9c5a4b`.
Verified 20 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 32310815 | 1 | performance |
| baseline/node:58 | 7417169 | 1 | performance |
| zeros/node:4 | 32188300 | 1 | performance |
| zeros/node:58 | 7417038 | 1 | performance |
| maximum/node:4 | 32165427 | 1 | performance |
| maximum/node:58 | 7417793 | 1 | performance |
| zero_point/node:4 | 32237814 | 1 | performance |
| zero_point/node:58 | 7420760 | 1 | performance |
| alternating/node:4 | 32226487 | 1 | performance |
| alternating/node:58 | 7416848 | 1 | performance |
| ramp/node:4 | 32263180 | 1 | performance |
| ramp/node:58 | 7415229 | 1 | performance |
| random_42/node:4 | 32311178 | 1 | performance |
| random_42/node:58 | 7416026 | 1 | performance |
| random_deadbeef/node:4 | 32311017 | 1 | performance |
| random_deadbeef/node:58 | 7416458 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
