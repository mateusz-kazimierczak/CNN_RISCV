# A0 isolated kernel investigation

Artifact: `5ef4c70258b1781568e907e488cbcedcd767126b08848fadc7ce71357b02ee87`.
Verified 8 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:1 | 277049718 | 1 | performance |
| baseline/node:4 | 228990399 | 1 | performance |
| baseline/node:8 | 125589275 | 1 | performance |
| baseline/node:15 | 75625351 | 1 | performance |
| baseline/node:58 | 164703520 | 1 | performance |
| baseline/node:61 | 10296433 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
