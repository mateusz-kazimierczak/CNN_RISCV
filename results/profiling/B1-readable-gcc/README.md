# B1 GCC investigation

Artifact: `0f266768d3abfabbbcf9a104b7618e2639443126e03a58c0d52c7cc475f8be06`.

Measured ELF: `fc7d6ba8e903609a6a71c012048abb881d6a90582a37f609eb92373e70d7ec37`.
Analysis ELF: `a05252bb5319545604668fbc5312311a88e33a9b868c2740a2ffa7e1d2e941d4`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-readable/model.cc | 9 |
| kernels/project/softmax.cc | 9 |
| kernels/project/quantization.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
