# TFLite Micro integration

This directory contains the minimal TFLM application for the quantized
EfficientNet-Lite0 model. It registers only the eight operators present in the
model and uses TFLM reference kernels.

TFLM is pinned to commit `9f638f18154dff868e7053572f089be845b2fbdf`.
The dependency is fetched into `.deps/tflite-micro` and is not vendored.

## Native validation

```bash
make run-native
```

This generates an aligned C++ array from the `.tflite`, downloads TFLM's
third-party build dependencies, builds the runtime, allocates a static tensor
arena, and performs one deterministic inference. The output checksum is
compared directly with the RV64IMC/Spike run.

The arena is 2 MiB. Both native and RV64 TFLM memory planners report 1,688,176
bytes in use, leaving about 399 KiB of headroom.

## RV64IMC and Spike

The repository includes a bare-metal RV64IMC target with HTIF console/exit
support for Spike. It uses the xPack RISC-V GCC toolchain (pinned and
checksum-verified by the Makefile), a custom startup file and linker script,
and target implementations for TFLM logging, time, and system setup. The
application and operator resolver are shared with the native build.

Prerequisites for building Spike itself are GNU Make, Device Tree Compiler,
and Boost. On macOS with Homebrew:

```bash
brew install make dtc boost
```

Build, audit, simulate, and verify one inference with:

```bash
make run-spike
```

Spike is pinned to commit `19609434bb3d83448eec8796e8f0367c868efbda`.
The run explicitly selects `--isa=rv64imc`. The ELF audit checks the declared
ISA and disassembles the complete executable, rejecting floating-point,
vector, and atomic instructions.

The linked ELF contains 5,556,652 bytes of text/read-only data, 2,936 bytes of
initialized data, and 2,097,872 bytes of BSS (mostly the 2 MiB tensor arena).
The linker additionally reserves a 1 MiB stack. These are correctness-first
baseline numbers; later B1 work can reduce both runtime code and arena size.

Expected verified output:

```text
TFLM EfficientNet-Lite0 inference: PASS
arena_used_bytes=1688176
output_top_index=21 output_top_score=48 output_sum=215
output_fnv1a=0x4b6a91e2
Spike output matches the native TFLM reference: PASS
```
