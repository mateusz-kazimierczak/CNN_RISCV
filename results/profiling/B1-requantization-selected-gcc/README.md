# B1 GCC investigation

Artifact: `b960d0c6680fdb137b186409a8861b67ca45b1e1c0a30c226ece99d15866fe48`.

Measured ELF: `2bd4ec9083ea15912fb2accafd926876d237088aacb231250990f3803c41ac1a`.
Analysis ELF: `267b9191152bec4e32187ad08314713f0d8240c8095aadde8464f81fef3d9825`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-requantization-selected/model.cc | 9 |
| kernels/project/softmax.cc | 9 |
| kernels/project/quantization.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
