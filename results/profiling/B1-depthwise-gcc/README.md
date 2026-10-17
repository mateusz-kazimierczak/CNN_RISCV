# B1 GCC investigation

Artifact: `b30c066204bf701a36c0e51234133b9512da237ac47d13a8f774d64a245c67e1`.

Measured ELF: `30987a4a2a400e386a5819b9498c82b448d4da46c84e93b20131b1e4216a4068`.
Analysis ELF: `9f3ad922801b8c5e398b1fd28453f8d7135b7f83b86963ec2d93570e60564c8a`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-depthwise/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
