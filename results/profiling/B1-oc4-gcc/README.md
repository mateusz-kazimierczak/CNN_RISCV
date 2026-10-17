# B1 GCC investigation

Artifact: `3e6204d2b3562ad04e5e229698fa10883db19dd90143d2cbffdaf6d15160e593`.

Measured ELF: `825f1f1aeb2b7e90a3b2c239f3110c243aec48a0a41ee011609e1a74cd84bdf1`.
Analysis ELF: `8933edb5d2aa2121af77bec66d414234757365583e5dec7094afe34f51ab819f`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-oc4/model.cc | 9 |
| kernels/reference/numerics.cc | 9 |
| .deps/tflite-micro/tensorflow/lite/kernels/internal/common.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
