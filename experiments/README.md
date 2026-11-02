# Reproducible experiments

The submission software progression is declared in [software.json](software.json).
The continuation is [the hardware-era workflow](hardware.md), with
[the complete submission progression](../results/submission/README.md).
Each stage adds options to the preceding stage; no kernel algorithms are changed
by this reorganization. A0 is the frozen LiteRT Micro baseline. B1.1 introduces
the SALT custom compiler with corrected static metadata; B1.2 is scalar
pointwise, B1.3 adds both fixed depthwise families, B1.4 adds stem GCC unrolling,
B1.5 selects the standalone runtime, B1.6 specializes requantization with the
accepted 25 inline nodes, and B1.7 switches directly to two pixels × two channels.
OC4 belongs to the historical experiments only.

From the repository root, after the [dependency setup](../README.md):

```sh
gmake software-plan
gmake software-experiments
```

`software-experiments` orders `software-checkpoints` before `software-report`,
including parallel make invocations. Run those targets separately to recapture
measurements or regenerate only the report. The complete report requires all
seven new captures through B1.7.

`software-checkpoints` builds the pinned oracle and profiler and runs their gates
and software kernel/sequence tests once. Run `gmake software-tests` to execute
those software tests independently. Each stage generates a distinct directory under `build/compiler/`, builds
native, intermediate-capture, sanitizer and RV64 programs, compares all native
test cases to the oracle, and executes ordinary Spike plus two full profiles.
The profiler compares all 1,000 public output bytes and exact event/PC histograms.
The first generated capture is B1.1; each later B1 stage embeds the immediately
preceding capture's summary and manifest identity. A0 uses the independent frozen
LiteRT measurement. Historical paths/configurations retain `B0` for LiteRT and
`A0` for SALT; they are mapped explicitly by `software.json`. Label-only changes
are recorded in each experiment receipt's `label_history`; capture bytes and
execution lineage remain unchanged.

The runner records expanded options, manifest hash, parent and capture identity
in each stage's `results/profiling/<checkpoint>/experiment.json`. It resumes only
completed matching selections after checking build inputs and capture integrity;
stale build inputs cause an error requiring regeneration. Use
`gmake software-checkpoints SOFTWARE_THROUGH=B1.4` to stop after an intermediate
stage. To deliberately regenerate completed stages, run:

```sh
uv run --python 3.12 --with-requirements tools/compiler/requirements.txt \
  python tools/run_software_experiments.py
```

Report generation revalidates captures, summaries, parent lineage, the frozen A0
baseline (historical B0), model/input/boundary compatibility, operator and instruction-mix conservation,
and exact reproduction of accepted final B1. It writes adjacent-stage and
presentation-grouped CSVs, per-family/per-node costs, footprint data, a portable
seven-bar chart (SVG, PNG and PDF), and a validation index in
[`results/profiling/B1-reordered/`](../results/profiling/B1-reordered/README.md).
B1.4 is measured separately; the chart groups B1.4 and B1.5 under compiler/runtime
cleanup. The saved intermediate table always uses adjacent measured parents.
`focus.csv` and the results README expose savings inside/outside each affected
operator family, load/store changes and storage tradeoffs. Per-stage
`verification.json` files preserve compact native/intermediate/sanitizer coverage
and build/report identities, with output files rehashed during report generation.
The plot renderer is pinned separately in `experiments/requirements.txt`.

Historical `compiler-b1-*-checkpoint` targets, results and the accepted B1
selection remain intact. The later X1–X5 ISA and RTL experiments are grouped by
`hardware.json` while retaining original capture identities and comparison
controls. See [EXPERIMENTS.md](../EXPERIMENTS.md) for the full map.

Compact results are tracked. Large build snapshots, native tensor captures,
ELFs and raw profiling histograms remain under ignored `build/`; a clean checkout
must regenerate them before `software-report` can revalidate the evidence.
Do not relabel old captures to claim a new optimization order.
