# X1 isolated kernel investigation

Artifact: `a2f88465ebcf136748eb33b5abb70dfc892f51c6d4af803cd391cbf8d54b75b2`.
Verified 20 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 36814111 | 1 | performance |
| baseline/node:58 | 11569490 | 1 | performance |
| zeros/node:4 | 36691596 | 1 | performance |
| zeros/node:58 | 11569359 | 1 | performance |
| maximum/node:4 | 36668723 | 1 | performance |
| maximum/node:58 | 11570114 | 1 | performance |
| zero_point/node:4 | 36741110 | 1 | performance |
| zero_point/node:58 | 11573081 | 1 | performance |
| alternating/node:4 | 36729783 | 1 | performance |
| alternating/node:58 | 11569169 | 1 | performance |
| ramp/node:4 | 36766476 | 1 | performance |
| ramp/node:58 | 11567550 | 1 | performance |
| random_42/node:4 | 36814474 | 1 | performance |
| random_42/node:58 | 11568347 | 1 | performance |
| random_deadbeef/node:4 | 36814313 | 1 | performance |
| random_deadbeef/node:58 | 11568779 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
