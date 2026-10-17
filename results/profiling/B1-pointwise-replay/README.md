# B1 isolated kernel investigation

Artifact: `560f219de0e5d077f671b7d718508437624d6697b567f9322572ec215e96dd5e`.
Verified 18 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 148281741 | 1 | performance |
| baseline/node:58 | 91258271 | 1 | performance |
| zeros/node:4 | 148257354 | 1 | performance |
| zeros/node:58 | 91258241 | 1 | performance |
| maximum/node:4 | 148245481 | 1 | performance |
| maximum/node:58 | 91258239 | 1 | performance |
| zero_point/node:4 | 148232600 | 1 | performance |
| zero_point/node:58 | 91258266 | 1 | performance |
| alternating/node:4 | 148232828 | 1 | performance |
| alternating/node:58 | 91258238 | 1 | performance |
| ramp/node:4 | 148263715 | 1 | performance |
| ramp/node:58 | 91258266 | 1 | performance |
| random_42/node:4 | 148281737 | 1 | performance |
| random_42/node:58 | 91258280 | 1 | performance |
| random_deadbeef/node:4 | 148281857 | 1 | performance |
| random_deadbeef/node:58 | 91258294 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
