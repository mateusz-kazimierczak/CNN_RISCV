# B1 GCC investigation

Artifact: `6694719c01a1e528f7da8bbf5f926be9138018e6d2e9c0d2ddafa7974aae6340`.

Measured ELF: `9163bb11c19bc357f87db4a22cd5c174c5100b2cd1d090774484b1022941f75b`.
Analysis ELF: `0d3a053890ff4eec71e81cd12f62d7e35f5e512c6eebfbbebd83669f4f730b9c`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-oc2/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
