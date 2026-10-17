# B1 GCC investigation

Artifact: `3125df6ef56b415c6bed804cf87c387222d08434054476d70e6e5346069891e4`.

Measured ELF: `627b914ded75e7c3ad6c07e076a9509db4e18968c22ba45822dea6a513c14c8d`.
Analysis ELF: `f5edf9d7045a785a2854b2595d9c150400b1225bc5355d36e8798013346ee0b4`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
