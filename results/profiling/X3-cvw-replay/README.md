# X3 isolated kernel investigation

Artifact: `6597301380b863dbbd30157680a8ffc4e65abf909c9b6655ecff90badbc5ab78`.
Verified 12 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 9853341 | 1 | performance |
| baseline/node:5 | 17248541 | 1 | performance |
| baseline/node:8 | 27425221 | 1 | performance |
| baseline/node:58 | 5012557 | 1 | performance |
| random_42/node:4 | 9853341 | 1 | performance |
| random_42/node:5 | 17248541 | 1 | performance |
| random_42/node:8 | 27425221 | 1 | performance |
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
