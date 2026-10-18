# X3 isolated kernel investigation

Artifact: `c9cf0c39c7c8c27db86a09a2818ea53e17a4fc05148f74bee03fad50cfed3c57`.
Verified 100 fixtures per build (native, sanitized, rv64).

| Fixture | Unit instructions | Harness overhead | Outcome |
|---|---:|---:|---|
| baseline/node:2 | 24261453 | 1 | performance |
| baseline/node:4 | 9853341 | 1 | performance |
| baseline/node:5 | 17248541 | 1 | performance |
| baseline/node:8 | 27425221 | 1 | performance |
| baseline/node:12 | 17393948 | 1 | performance |
| baseline/node:15 | 31298687 | 1 | performance |
| baseline/node:19 | 2743604 | 1 | performance |
| baseline/node:22 | 6579785 | 1 | performance |
| baseline/node:26 | 6579785 | 1 | performance |
| baseline/node:33 | 24308261 | 1 | performance |
| baseline/node:56 | 4643150 | 1 | performance |
| baseline/node:58 | 5012557 | 1 | performance |
| zeros/node:2 | 24261453 | 1 | performance |
| zeros/node:4 | 9853341 | 1 | performance |
| zeros/node:5 | 17248541 | 1 | performance |
| zeros/node:8 | 27425221 | 1 | performance |
| zeros/node:12 | 17393948 | 1 | performance |
| zeros/node:15 | 31298687 | 1 | performance |
| zeros/node:19 | 2743604 | 1 | performance |
| zeros/node:22 | 6579785 | 1 | performance |
| zeros/node:26 | 6579785 | 1 | performance |
| zeros/node:33 | 24308261 | 1 | performance |
| zeros/node:56 | 4643150 | 1 | performance |
| zeros/node:58 | 5012557 | 1 | performance |
| maximum/node:2 | 24261453 | 1 | performance |
| maximum/node:4 | 9853341 | 1 | performance |
| maximum/node:5 | 17248541 | 1 | performance |
| maximum/node:8 | 27425221 | 1 | performance |
| maximum/node:12 | 17393948 | 1 | performance |
| maximum/node:15 | 31298687 | 1 | performance |
| maximum/node:19 | 2743604 | 1 | performance |
| maximum/node:22 | 6579785 | 1 | performance |
| maximum/node:26 | 6579785 | 1 | performance |
| maximum/node:33 | 24308261 | 1 | performance |
| maximum/node:56 | 4643150 | 1 | performance |
| maximum/node:58 | 5012557 | 1 | performance |
| zero_point/node:2 | 24261453 | 1 | performance |
| zero_point/node:4 | 9853341 | 1 | performance |
| zero_point/node:5 | 17248541 | 1 | performance |
| zero_point/node:8 | 27425221 | 1 | performance |
| zero_point/node:12 | 17393948 | 1 | performance |
| zero_point/node:15 | 31298687 | 1 | performance |
| zero_point/node:19 | 2743604 | 1 | performance |
| zero_point/node:22 | 6579785 | 1 | performance |
| zero_point/node:26 | 6579785 | 1 | performance |
| zero_point/node:33 | 24308261 | 1 | performance |
| zero_point/node:56 | 4643150 | 1 | performance |
| zero_point/node:58 | 5012557 | 1 | performance |
| alternating/node:2 | 24261453 | 1 | performance |
| alternating/node:4 | 9853341 | 1 | performance |
| alternating/node:5 | 17248541 | 1 | performance |
| alternating/node:8 | 27425221 | 1 | performance |
| alternating/node:12 | 17393948 | 1 | performance |
| alternating/node:15 | 31298687 | 1 | performance |
| alternating/node:19 | 2743604 | 1 | performance |
| alternating/node:22 | 6579785 | 1 | performance |
| alternating/node:26 | 6579785 | 1 | performance |
| alternating/node:33 | 24308261 | 1 | performance |
| alternating/node:56 | 4643150 | 1 | performance |
| alternating/node:58 | 5012557 | 1 | performance |
| ramp/node:2 | 24261453 | 1 | performance |
| ramp/node:4 | 9853341 | 1 | performance |
| ramp/node:5 | 17248541 | 1 | performance |
| ramp/node:8 | 27425221 | 1 | performance |
| ramp/node:12 | 17393948 | 1 | performance |
| ramp/node:15 | 31298687 | 1 | performance |
| ramp/node:19 | 2743604 | 1 | performance |
| ramp/node:22 | 6579785 | 1 | performance |
| ramp/node:26 | 6579785 | 1 | performance |
| ramp/node:33 | 24308261 | 1 | performance |
| ramp/node:56 | 4643150 | 1 | performance |
| ramp/node:58 | 5012557 | 1 | performance |
| random_42/node:2 | 24261453 | 1 | performance |
| random_42/node:4 | 9853341 | 1 | performance |
| random_42/node:5 | 17248541 | 1 | performance |
| random_42/node:8 | 27425221 | 1 | performance |
| random_42/node:12 | 17393948 | 1 | performance |
| random_42/node:15 | 31298687 | 1 | performance |
| random_42/node:19 | 2743604 | 1 | performance |
| random_42/node:22 | 6579785 | 1 | performance |
| random_42/node:26 | 6579785 | 1 | performance |
| random_42/node:33 | 24308261 | 1 | performance |
| random_42/node:56 | 4643150 | 1 | performance |
| random_42/node:58 | 5012557 | 1 | performance |
| random_deadbeef/node:2 | 24261453 | 1 | performance |
| random_deadbeef/node:4 | 9853341 | 1 | performance |
| random_deadbeef/node:5 | 17248541 | 1 | performance |
| random_deadbeef/node:8 | 27425221 | 1 | performance |
| random_deadbeef/node:12 | 17393948 | 1 | performance |
| random_deadbeef/node:15 | 31298687 | 1 | performance |
| random_deadbeef/node:19 | 2743604 | 1 | performance |
| random_deadbeef/node:22 | 6579785 | 1 | performance |
| random_deadbeef/node:26 | 6579785 | 1 | performance |
| random_deadbeef/node:33 | 24308261 | 1 | performance |
| random_deadbeef/node:56 | 4643150 | 1 | performance |
| random_deadbeef/node:58 | 5012557 | 1 | performance |
| scalar_dot/K=16 | 230 | 1 | performance |
| xqmac8_dot/K=16 | 36 | 1 | performance |
| scalar_dot/K=320 | 3878 | 1 | performance |
| xqmac8_dot/K=320 | 302 | 1 | performance |

- Setup, restoration, poisoning and complete byte comparisons are outside the region.
- Scalar dot measurements include cc_dot's existing int64 overflow checks.
- Error outcomes are diagnostics, not successful performance results.
- Replay and production ELFs have separate identities; isolated counts do not substitute for full inference.
- Spike retirements are not hardware cycles.
