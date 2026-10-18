# X1 isolated kernel investigation

Artifact: `2bd44789e7bdc9507fda31223ae975a5b68aef96ca6d398adc2a3706ff05f232`.
Verified 20 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:4 | 41631006 | 1 | performance |
| baseline/node:58 | 16689543 | 1 | performance |
| zeros/node:4 | 41508491 | 1 | performance |
| zeros/node:58 | 16689412 | 1 | performance |
| maximum/node:4 | 41485618 | 1 | performance |
| maximum/node:58 | 16690167 | 1 | performance |
| zero_point/node:4 | 41558005 | 1 | performance |
| zero_point/node:58 | 16693134 | 1 | performance |
| alternating/node:4 | 41546678 | 1 | performance |
| alternating/node:58 | 16689222 | 1 | performance |
| ramp/node:4 | 41583371 | 1 | performance |
| ramp/node:58 | 16687603 | 1 | performance |
| random_42/node:4 | 41631369 | 1 | performance |
| random_42/node:58 | 16688400 | 1 | performance |
| random_deadbeef/node:4 | 41631208 | 1 | performance |
| random_deadbeef/node:58 | 16688832 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
