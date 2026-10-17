# Stage 0 reference fixtures

`baseline-output.bin` contains all 1,000 UINT8 output bytes for B0's seed-1 input.
Its SHA-256 is `6df1afb3691f347c05e8e671989c0c2121a6a295ec52a38b11c1422db03e070e`.
Its FNV-1a is `0x4b6a91e2`.

`oracle-golden.json` records output metadata and 510 node tensor SHA-256 values
from pinned native TFLM. Seven scenarios complete all 64 nodes. The all-131
scenario records an actual reference SIGABRT at node 62, with the 62 completed
outputs preserved; it has no final output hash. This failure also reproduces
using the original memory-reuse planner and arena size.

The full arrays are retained in ignored `build/compiler/oracle/` captures and
are reproducible with `gmake compiler-oracle`. The capture manifest records the
actual oracle executable, source/build hashes, reference revision, and input
generation. No build or test target rewrites these tracked fixtures. Changes to
them require independently checking the reference and reviewing the numerical
difference. See [the compiler guide](../../../docs/compiler.md).

`tflite_builder.py` constructs tiny FlatBuffers in memory for Stage 1 tests.
It supplies valid examples of all eight operator kinds and deliberate malformed
versions, shapes, quantization, buffers, options, and graph edges. These tests
exercise source decoding without rewriting the tracked EfficientNet model or
the Stage 0 golden files.
