# X4 isolated kernel investigation

Artifact: `b102658c498377bdff91b07bfeee958a74a432db4bd9dde0fdadc6a3fcf43d63`.
Verified 40 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:2 | 7868784 | 1 | performance |
| baseline/node:4 | 9853341 | 1 | performance |
| baseline/node:5 | 5646728 | 1 | performance |
| baseline/node:8 | 8394233 | 1 | performance |
| baseline/node:12 | 2895794 | 1 | performance |
| baseline/node:15 | 4896844 | 1 | performance |
| baseline/node:19 | 878091 | 1 | performance |
| baseline/node:22 | 1785064 | 1 | performance |
| baseline/node:26 | 1785064 | 1 | performance |
| baseline/node:30 | 2559120 | 1 | performance |
| baseline/node:33 | 3625103 | 1 | performance |
| baseline/node:37 | 3625103 | 1 | performance |
| baseline/node:41 | 906442 | 1 | performance |
| baseline/node:44 | 1565677 | 1 | performance |
| baseline/node:48 | 1565677 | 1 | performance |
| baseline/node:52 | 1565677 | 1 | performance |
| baseline/node:56 | 1119461 | 1 | performance |
| baseline/node:58 | 5012557 | 1 | performance |
| random_42/node:2 | 7868784 | 1 | performance |
| random_42/node:4 | 9853341 | 1 | performance |
| random_42/node:5 | 5646728 | 1 | performance |
| random_42/node:8 | 8394233 | 1 | performance |
| random_42/node:12 | 2895794 | 1 | performance |
| random_42/node:15 | 4896844 | 1 | performance |
| random_42/node:19 | 878091 | 1 | performance |
| random_42/node:22 | 1785064 | 1 | performance |
| random_42/node:26 | 1785064 | 1 | performance |
| random_42/node:30 | 2559120 | 1 | performance |
| random_42/node:33 | 3625103 | 1 | performance |
| random_42/node:37 | 3625103 | 1 | performance |
| random_42/node:41 | 906442 | 1 | performance |
| random_42/node:44 | 1565677 | 1 | performance |
| random_42/node:48 | 1565677 | 1 | performance |
| random_42/node:52 | 1565677 | 1 | performance |
| random_42/node:56 | 1119461 | 1 | performance |
| random_42/node:58 | 5012557 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
