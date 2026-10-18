# B1 GCC investigation

Artifact: `231868ce1abf84b8abb227994ce892750188f7a4a08ea8c54416870eb35547d1`.

Measured ELF: `0cced4586d318d03a6615211ca992834b6e707e842a19ebf2d1807cbe14eb694`.
Analysis ELF: `f061802d87ab528cd6aefd10dcd7a7ff9a0caa2f2297f8454c53fe2ddab5f6ad`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-requantization-inline/model.cc | 9 |
| kernels/project/softmax.cc | 9 |
| kernels/project/quantization.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
