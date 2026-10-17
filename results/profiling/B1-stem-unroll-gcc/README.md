# B1 GCC investigation

Artifact: `0d00fd587086f8d9a4fced1a4e7809cecb9e9a51ebe394bfbf8aea9f7f28393a`.

Measured ELF: `03d836651e16c59160f26287a1f1ac1be991ecfc8ff11bfd53fe7afcafe77e71`.
Analysis ELF: `a035012731ddce79fe2b0a2cb768c536314d5c15c3be1f5f88cdc54a22550625`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-stem/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
