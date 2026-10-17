# B1 GCC investigation

Artifact: `5d38fe2f566ba67d796cdd0fbffbaa38b2eb6803f5ca912d0c0acc9635acae2c`.

Measured ELF: `5445775f5503b3a6426456074d69ab41fb225f268f28724431cca6d1b1a42bf8`.
Analysis ELF: `5fc77290d818b9e3df37d89686b46d96e62d631da6dd3f4e72ad0f666b3ad372`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-standalone/model.cc | 9 |
| kernels/project/softmax.cc | 9 |
| kernels/project/quantization.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
