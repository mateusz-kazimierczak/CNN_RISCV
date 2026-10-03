# Host utilities

These Python scripts run on the development machine. They inspect or generate
inputs to the C++ build; the RISC-V program does not execute Python.
Run commands from the repository root.

## Inspect the model

[inspect_tflite.py](inspect_tflite.py) reads FlatBuffer tensor and operator
metadata, checks weight/bias quantization, and estimates MACs from tensor
shapes. It does not run inference. The model and the recorded findings are
described in [models/README.md](../models/README.md).

This command uses `uv` to supply the optional inspection dependencies:

```bash
uv run --python 3.12 --with tflite --with numpy \
  python tools/inspect_tflite.py models/efficientnet-lite0-int8.tflite
```

It prints JSON. Add `--output path/to/report.json` to save it. The checked-in
report is `models/efficientnet-lite0-int8.audit.json`. The MAC estimate covers
Conv2D, depthwise convolution, and fully connected operators in this fixed,
single-batch model; it is not a simulator instruction count. Finding no
floating-point tensors does not exclude floating-point scale calculations
inside the runtime's operator preparation.

## Embed the model

[generate_cc_array.py](generate_cc_array.py) copies the model bytes into an
aligned constant C++ array and emits a declaration header. The array still
contains the FlatBuffer graph and weights; this is embedding, not graph or
kernel compilation. It uses only Python's standard library.

```bash
gmake model-data
```

The Makefile generates `tflm/generated/model_data.cc` and `model_data.h`.
These files are ignored and should be regenerated from the tracked `.tflite`.
The generator is tailored to this build: its source includes `model_data.h`.

## Audit the executable

[audit_rv64_elf.py](audit_rv64_elf.py) invokes the cross toolchain's `readelf`
and `objdump` to inspect the linked ELF. It screens the declared base ISA and
decoded mnemonics for floating-point, vector, and atomic instructions.

```bash
gmake audit-rv64
```

The decoded count is the number of static instruction entries in the
disassembly, not instructions retired during inference. Software floating
point helpers contain integer instructions, so they can pass this check.
This script is a focused screen for the project's excluded instruction
families, not a complete validator for every possible RISC-V extension.
`gmake run-spike` additionally executes the program with Spike restricted to
`--isa=rv64imc` and compares the output against the stored reference values.
