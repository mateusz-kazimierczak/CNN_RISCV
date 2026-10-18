# CV-Wally B0/B1 ASIC baseline: prepared, blocked before mapping

The exact pinned B0/B1 simulation configuration has been regenerated and its
header SHA-256 verified as
`492989e18ecf6cd27aaed40f3f0ac0153c9dd41a2c336f9740c801e3cfdf4a21`.
The synthesis boundary is the upstream `wallypipelinedcore` wrapper with both
16 KiB caches and unchanged `USE_SRAM=0`; it excludes the external behavioral
128 MiB simulation RAM. Cache arrays would map to standard cells, not SRAM macros.

The authorized smoke job `20261018T070704Z-71a7d2bf0c54` exited 255 with:

```text
Fatal: Design Compiler is not enabled. (DCSH-1)
```

The log was fetched to
`synth/results/20261018T070704Z-71a7d2bf0c54/logs/dc.log` (ignored raw artifacts).
No full-core synthesis was submitted. There are no area/timing measurements.
DC release selection and library readability are verified; DC initialization,
library loading and compilation have not succeeded. Course CAD staff need to
resolve the startup/entitlement failure before the smoke/core run can continue.

The [workflow guide](../../../synth/README.md) documents home-directory guards,
temporary/cache paths, shared-server limits and the scope of the storage policy.
The shell-only remote storage/resource probe passed without running DC; its
output and the failed-smoke metadata are retained in [status.json](status.json).

Regenerate the manifest with `python3 tools/cvw/prepare_synth.py`; inspect it with
`python3 tools/nthu_synth.py submit --config synth/configs/cv_wally_b0.json --dry-run`.
After CAD staff resolve the DC failure, obtain a successful fetched smoke run
before using `--allow-full-core --smoke-job <id>` for the baseline submission.
