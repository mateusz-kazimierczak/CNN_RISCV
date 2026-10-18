# B1 GCC investigation

Artifact: `ccfb988759bc34900922dc93bc3e2893f66530568d7a1cbc6c75886e5863bb0a`.

Measured ELF: `d9f1f72d52c386f39edb5f4b331c5d6b0351f26f18dfa50daa0d1e6fcc5914d9`.
Analysis ELF: `15a44b6bbe8cb4269aa70e98da8472e6766337c45487025940e454db5f9056c8`.

All allocated sections and loadable segments match, including addresses and data. Debug/dump metadata has a separate identity.

| Executable translation unit | Diagnostic stages |
|---|---:|
| build/compiler/B1-spatial2-oc2/model.cc | 9 |
| kernels/project/softmax.cc | 9 |
| kernels/project/quantization.cc | 9 |
| tools/compiler/a0_target.cc | 9 |
| tflm/platform/rv64imc/syscalls.cc | 9 |

GCC remarks and IR are compiler evidence, not retirement measurements. RTL instruction numbers are not machine addresses.
