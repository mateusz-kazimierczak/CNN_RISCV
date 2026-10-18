# X2 isolated kernel investigation

Artifact: `876bdbf31aff14fccaf47e9fa2907be671a7e19fe51aa83bf86790b49e9f84b6`.
Verified 44 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 10455452 | 1 | performance |
| baseline/node:10 | 1053721 | 1 | performance |
| baseline/node:33 | 24308261 | 1 | performance |
| baseline/node:37 | 24308261 | 1 | performance |
| baseline/node:58 | 5652879 | 1 | performance |
| zeros/node:4 | 10455452 | 1 | performance |
| zeros/node:10 | 1053721 | 1 | performance |
| zeros/node:33 | 24308261 | 1 | performance |
| zeros/node:37 | 24308261 | 1 | performance |
| zeros/node:58 | 5652879 | 1 | performance |
| maximum/node:4 | 10455452 | 1 | performance |
| maximum/node:10 | 1053721 | 1 | performance |
| maximum/node:33 | 24308261 | 1 | performance |
| maximum/node:37 | 24308261 | 1 | performance |
| maximum/node:58 | 5652879 | 1 | performance |
| zero_point/node:4 | 10455452 | 1 | performance |
| zero_point/node:10 | 1053721 | 1 | performance |
| zero_point/node:33 | 24308261 | 1 | performance |
| zero_point/node:37 | 24308261 | 1 | performance |
| zero_point/node:58 | 5652879 | 1 | performance |
| alternating/node:4 | 10455452 | 1 | performance |
| alternating/node:10 | 1053721 | 1 | performance |
| alternating/node:33 | 24308261 | 1 | performance |
| alternating/node:37 | 24308261 | 1 | performance |
| alternating/node:58 | 5652879 | 1 | performance |
| ramp/node:4 | 10455452 | 1 | performance |
| ramp/node:10 | 1053721 | 1 | performance |
| ramp/node:33 | 24308261 | 1 | performance |
| ramp/node:37 | 24308261 | 1 | performance |
| ramp/node:58 | 5652879 | 1 | performance |
| random_42/node:4 | 10455452 | 1 | performance |
| random_42/node:10 | 1053721 | 1 | performance |
| random_42/node:33 | 24308261 | 1 | performance |
| random_42/node:37 | 24308261 | 1 | performance |
| random_42/node:58 | 5652879 | 1 | performance |
| random_deadbeef/node:4 | 10455452 | 1 | performance |
| random_deadbeef/node:10 | 1053721 | 1 | performance |
| random_deadbeef/node:33 | 24308261 | 1 | performance |
| random_deadbeef/node:37 | 24308261 | 1 | performance |
| random_deadbeef/node:58 | 5652879 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
