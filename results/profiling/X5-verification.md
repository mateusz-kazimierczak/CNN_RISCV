# Validated X5 packed RGB stem checkpoint

| Metric | X4 | X5 |
|---|---:|---:|
| Inference instructions | 229,114,977 | 167,729,178 |
| Stem instructions | 69,472,265 | 8,086,466 |
| Stem loads | 27,628,124 | 2,757,680 |
| Stem scalar multiplications | 10,773,600 | 0 |

Full-inference reduction: **26.79%** (1.366× instruction-count ratio).
Stem reduction: **88.36%** (8.591× instruction-count ratio).
All 63 untargeted execution units retain identical metrics.

## Implementation

The compiler prepares 32-byte weight rows (27 original OHWI values plus five zero lanes), and border-specific corrected biases. Each output pixel gathers one signed RGB patch into four registers, reused across all 32 output channels. Four existing Xqmac8 instructions and one unchanged Xrequant produce each output. Invalid spatial and tail lanes are zero. INT32 prefix bounds are proved offline; no new ISA or whole-image im2col buffer is introduced.

## Validation

- 243 compiler regressions across all 23 modules and five profiler tests pass.
- Independent INT64 accumulator checks pass 64 synthetic cases under ASan/UBSan, covering borders, small and odd dimensions, extreme data, absent biases, signed offsets, unaligned RGB input, and varied output-channel counts.
- Native, full-tensor capture and ASan/UBSan builds match all eight reference cases. Capture and sanitizer modes each compare 510 complete tensors; the known zero-point-input Softmax outcome remains status 2 after 62 matching tensors.
- Baseline and random_42 full RV64 inference match all 1,000 output bytes. Two full event/PC profiles agree exactly. The stem retires precisely 1,605,632 Xqmac8 and 401,408 Xrequant instructions; padded physical work is 12,845,056 lane products.
- 52 replay fixtures pass native, ASan/UBSan and RV64, with repeated profiles: stem plus five control layers across eight cases, plus four dot controls.
- B1/X1/X2/X3/X4 allocated sections and load segments remain byte-identical. Existing X4 ISA library identities and frozen B0 data are unchanged.

## Footprint and next bottlenecks

Prepared constants grow by 51,712 bytes (50,176-byte region map, 512-byte corrected biases, 1,024-byte packed weights). Executable code shrinks from 38,572 to 38,140 bytes. Activation workspace remains 1,505,280 bytes.
Pointwise layers now account for 98,321,810 instructions (58.6%), depthwise layers 50,682,862 (30.2%), and the stem 8,086,466 (4.8%). The largest single node is pointwise node 4 at 9,853,341 instructions (5.9%).
These are retired instruction counts, not cache misses or hardware cycle speedups. X5 hardware performance has not been measured.

Reproduce with `make compiler-x5-checkpoint`. The adjacent JSON binds captures, binaries, numerical evidence, replay, tests and legacy controls.
