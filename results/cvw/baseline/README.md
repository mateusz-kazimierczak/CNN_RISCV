# CV-Wally baseline bring-up

Preserved B0 and accepted software B1 run on the same pinned RV64IMC core.
Full-model metrics require clean exit, exact retirement agreement and
complete 1,000-byte reference-output comparison.

| Configuration | State | Invocation retirements | Invocation cycles |
|---|---|---:|---:|
| B0 | PASS | 4,867,278,370 | 5,397,408,750 |
| B1 | PASS | 1,576,585,275 | 1,679,179,098 |

The directed fixture passes 19 retirements, complete unaligned output
comparison, repeated HTIF acknowledgement, wrong-count rejection and
incomplete-run rejection. Details and partial progress are in [summary.json](summary.json).

A partial progress count is not a completed inference metric. Physical
clock frequency and area remain unmeasured in this simulation checkpoint.

[Configuration, scope and reproduction](../../../docs/cvw-verilator.md).
