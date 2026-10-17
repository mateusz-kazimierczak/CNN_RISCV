# A0 GCC investigation

Artifact: `de4088ac66ec3f163d3deed4c082f16889a372cd933ba0c2e2d6b72695b8c552`.

Measured ELF: `ad7135f142507b3e727e61bca4b0e8dc27eff8c4e6df5c6e85aa940b103f604e`.
Analysis ELF: `4ed76ef4476ede4df3fd33ce783cdf551393cab98086b822ead3350b46e57a49`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/A0/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
