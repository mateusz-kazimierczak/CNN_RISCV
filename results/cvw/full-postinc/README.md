# Full-model custom-instruction RTL simulations

Exact accepted checkpoint ELFs on separate pinned CV-Wally overlays. Final results require all 1,000 reference bytes, exact total and per-extension retirements, clean exit, and directed monitor gates.

| Checkpoint | Status | Instructions | Cycles |
|---|---|---:|---:|
| B0 | PASS | 4,867,278,370 | 5,397,408,750 |
| B1 | PASS | 1,576,585,275 | 1,679,179,098 |
| X1 | PASS | 594,975,670 | 687,052,832 |
| X2 | PASS | 436,158,109 | 517,650,202 |
| X3 | RUNNING | pending | pending |

Values are simulated cycles; physical clock frequency and area remain unmeasured. See [setup and reproduction](../../../docs/cvw-verilator.md#custom-instruction-full-inference) and [machine-readable evidence](summary.json).
