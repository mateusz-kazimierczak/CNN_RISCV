# Experiment and evidence index

Start with [the unified submission package](results/submission/README.md).
The [software workflow](experiments/README.md) and
[hardware-era workflow](experiments/hardware.md) are driven by
[software.json](experiments/software.json) and
[hardware.json](experiments/hardware.json).

Main presentation: **A0 → B1.1 → B1.2 → B1.3 → B1.5 → B1.6 → B1.7 → X1 → X2 → X3 → X4 → X5**.
B1.4 remains measured inside the B1.5 group. X1.1–X1.4 and X2.1–X2.3 retain
ISA introduction and compiler refinements; D1 remains a software-only control
before X4. X3.broad is an alternative from X2, and X5 adds no new ISA.

```sh
gmake software-experiments
gmake hardware-experiments
gmake submission-report
```

The final command regenerates the cross-checked reports from saved evidence.
Hardware captures are reused only after validation; `gmake hardware-recapture`
creates separate fresh Spike captures. RTL rerun/collection remains the pinned
Linux/WSL workflow, with exact workload contracts.
`gmake submission-package` produces the local source/evidence archive and
checksum under `build/submission/`, with an inventory of every packaged file.

| Comparison | Reproduce | Evidence |
|---|---|---|
| A0: frozen LiteRT (stored as B0) | `gmake profile-spike` | [B0](results/profiling/B0/README.md) |
| B1.1 custom compiler → B1.7 | `gmake software-experiments` | [Cumulative results](results/profiling/B1-reordered/README.md) |
| Hardware-era stages and archived RTL cycles | `gmake hardware-experiments` | [Hardware progression](results/profiling/hardware-progression/README.md) |
| Historical accepted B1 | `gmake compiler-b1-software-checkpoint` | [Selection](results/profiling/B1-software/selection.json), [history](docs/B1-software-history.md) |
| Packed MAC, selected 2×4 schedule | `gmake compiler-x1-tile2x4-checkpoint` | [X1](results/profiling/X1-tile2x4/README.md) |
| Requantization and scheduling | `gmake compiler-x2-optimized-checkpoint` | [X2](results/profiling/X2-optimized/README.md) |
| Post-increment | `gmake compiler-x3-checkpoint` | [X3-selected](results/profiling/X3-selected/README.md) |
| Software depthwise control and bank extension | `gmake compiler-x4-checkpoint` | [D1](results/profiling/D1/README.md), [X4](results/profiling/X4/README.md) |
| Packed RGB stem | `gmake compiler-x5-checkpoint` | [X5](results/profiling/X5/README.md) |
| CV-Wally RTL gates and replay | `gmake cvw-xqmac8-checkpoint` (and corresponding extension targets) | [RTL guides](DESIGN.md), `results/cvw/` |
| Hardware cost | Platform-specific synthesis workflow | [Synthesis setup](synth/README.md), `results/synthesis/` |

The retained low-level targets in this table preserve historical folder names.
Submission X1 is `X1-tile2x4`; folder `X1` is X1.1. Submission X2 is
`X2-optimized`; folder `X2` is X2.1. The new production X2.2 checkpoint is
`X2-submission-02-outline`. Main X4 includes D1, while the ISA-only ablation
compares D1 → X4. D1 has no separate full-model cycle result.

Whole-stage instruction gains include recorded software tuning. X1's selected
2×4 packed schedule differs from B1.7's scalar 2×2 schedule. The manifest and
node-level comparisons retain these distinctions; they do not attribute every
whole-stage change to an opcode alone.

Use [the submission checklist](docs/submission.md) to distinguish available
evidence from deliverables still requiring final assembly.
