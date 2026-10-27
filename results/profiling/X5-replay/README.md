# X5 isolated kernel investigation

Artifact: `51ff994f78376506f6b5f1beb39cadc1c60c58e00fde02bf59f44cb26db7a857`.
Verified 52 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:1 | 8086466 | 1 | performance |
| baseline/node:2 | 7868784 | 1 | performance |
| baseline/node:4 | 9853341 | 1 | performance |
| baseline/node:8 | 8394233 | 1 | performance |
| baseline/node:58 | 5012557 | 1 | performance |
| baseline/node:61 | 6892036 | 1 | performance |
| zeros/node:1 | 8086466 | 1 | performance |
| zeros/node:2 | 7868784 | 1 | performance |
| zeros/node:4 | 9853341 | 1 | performance |
| zeros/node:8 | 8394233 | 1 | performance |
| zeros/node:58 | 5012557 | 1 | performance |
| zeros/node:61 | 6892036 | 1 | performance |
| maximum/node:1 | 8086466 | 1 | performance |
| maximum/node:2 | 7868784 | 1 | performance |
| maximum/node:4 | 9853341 | 1 | performance |
| maximum/node:8 | 8394233 | 1 | performance |
| maximum/node:58 | 5012557 | 1 | performance |
| maximum/node:61 | 6892036 | 1 | performance |
| zero_point/node:1 | 8086466 | 1 | performance |
| zero_point/node:2 | 7868784 | 1 | performance |
| zero_point/node:4 | 9853341 | 1 | performance |
| zero_point/node:8 | 8394233 | 1 | performance |
| zero_point/node:58 | 5012557 | 1 | performance |
| zero_point/node:61 | 6892036 | 1 | performance |
| alternating/node:1 | 8086466 | 1 | performance |
| alternating/node:2 | 7868784 | 1 | performance |
| alternating/node:4 | 9853341 | 1 | performance |
| alternating/node:8 | 8394233 | 1 | performance |
| alternating/node:58 | 5012557 | 1 | performance |
| alternating/node:61 | 6892036 | 1 | performance |
| ramp/node:1 | 8086466 | 1 | performance |
| ramp/node:2 | 7868784 | 1 | performance |
| ramp/node:4 | 9853341 | 1 | performance |
| ramp/node:8 | 8394233 | 1 | performance |
| ramp/node:58 | 5012557 | 1 | performance |
| ramp/node:61 | 6892036 | 1 | performance |
| random_42/node:1 | 8086466 | 1 | performance |
| random_42/node:2 | 7868784 | 1 | performance |
| random_42/node:4 | 9853341 | 1 | performance |
| random_42/node:8 | 8394233 | 1 | performance |
| random_42/node:58 | 5012557 | 1 | performance |
| random_42/node:61 | 6892036 | 1 | performance |
| random_deadbeef/node:1 | 8086466 | 1 | performance |
| random_deadbeef/node:2 | 7868784 | 1 | performance |
| random_deadbeef/node:4 | 9853341 | 1 | performance |
| random_deadbeef/node:8 | 8394233 | 1 | performance |
| random_deadbeef/node:58 | 5012557 | 1 | performance |
| random_deadbeef/node:61 | 6892036 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
