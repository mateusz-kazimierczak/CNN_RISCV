# TFLite Micro integration

This directory contains the minimal TFLM application for the quantized
EfficientNet-Lite0 model. It registers only the eight operators present in the
model and uses TFLM reference kernels.

Start with [the project README](../README.md) for prerequisites and navigation.
The [RV64IMC platform guide](platform/rv64imc/README.md) explains startup,
memory layout, logging, and exit handling.

TFLM is pinned to commit `9f638f18154dff868e7053572f089be845b2fbdf`.
The dependency is fetched into `.deps/tflite-micro` and is not vendored.

## Native validation

```bash
gmake run-native
```

This generates an aligned C++ array from the `.tflite`, downloads TFLM's
third-party build dependencies, builds the runtime, allocates a static tensor
arena, and performs one deterministic inference. The output checksum is
compared directly with the RV64IMC/Spike run.

The arena is 2 MiB. Both native and RV64 TFLM memory planners report 1,688,176
bytes in use, leaving about 399 KiB of headroom.

## Application flow

Read [efficientnet_lite0.cc](efficientnet_lite0.cc) from `main()`:

1. Initialize platform support and access the embedded FlatBuffer model.
2. Register the eight required operator types in `MicroMutableOpResolver<8>`.
3. Construct the interpreter with a static tensor arena and call
   `AllocateTensors()` to prepare operators and plan their buffers.
4. Check the model's UINT8 input `[1,224,224,3]` and output `[1,1000]`.
5. Fill the input with deterministic bytes, then call `Invoke()` once.
6. Report arena usage, the largest output byte, and a checksum of every output.

The resolver size is the number of distinct operator types, not the model's
64 operator nodes. Both `QUANTIZE` nodes convert between the public UINT8
representation and the internal INT8 representation. Their names do not
imply floating-point tensors.

`TFLM EfficientNet-Lite0 inference: PASS` means the application successfully
prepared and invoked the model. The Makefile's `run-spike` target then checks
the output against the recorded native reference values. The fixed input
supports reproducibility; image preprocessing and accuracy evaluation are
additional work.

## Setup and inference arithmetic

The host embeds model bytes, then compiles the application, interpreter,
kernels, and platform support. In the RV64 build, all of that code executes
on the target, including `AllocateTensors()`.

`AllocateTensors()` invokes operator `Prepare()` callbacks. These read
floating-point quantization scales and calculate integer multipliers and
shifts. For example, convolution preparation derives
`input_scale * weight_scale / output_scale` for each output channel. The
current RV64 build implements this floating-point setup through compiler
software helpers and math library routines running on integer instructions.
It does not define `TFLITE_EMULATE_FLOAT`, and it does not require an FPU.

`Invoke()` dispatches to the integer reference kernels for this model.
Convolution/FC outputs are requantized with integer fixed-point multiplication,
rounding, shifts, zero-point adjustment, and clamping. Quantized softmax also
uses integer arithmetic. If collecting dynamic instruction counts, distinguish
inference from preparation, synthetic input generation, and output reporting.

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
gmake run-spike
```

Spike is pinned to commit `19609434bb3d83448eec8796e8f0367c868efbda`.
The run explicitly selects `--isa=rv64imc`. The ELF audit checks the declared
ISA and disassembles the executable to screen for floating-point, vector,
and atomic instructions. Its decoded instruction count is static, and its
checks do not detect software floating-point arithmetic.

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
