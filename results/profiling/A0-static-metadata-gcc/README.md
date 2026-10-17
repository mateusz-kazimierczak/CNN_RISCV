# A0 GCC investigation

Artifact: `5b24d2f9614c91dea3e884b5fd4b4c22cd95c45f3a797ba0958f643e74f9f571`.

Measured ELF: `f44380f9d25886f511bfae3f4ece65acfb830b7141ec54dc1d761c06dee31039`.
Analysis ELF: `1d31d526095d54d8846aa7955d127f293839a3ccb6c01a6d1a38a84ef336b649`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/A0/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
