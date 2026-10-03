# B0: EfficientNet-Lite0 RV64IMC instruction profile

Two complete captures matched exactly. The ordinary and profiling simulator produced the native reference checksum `0x4b6a91e2`; profiling and ordinary ELF loadable sections are identical.

`Invoke()`: **4,867,278,370 retired instructions**. `AllocateTensors()`: 14,532,148, measured separately.
Logical MACs: 385,187,552; executed products (excluding skipped padding): 381,239,488.
Executed products/instruction: 0.078327; memory instructions/product: 3.267184.
Interpreter overhead: 4,820 instructions. Custom instruction utilization: 0.

These are ISA-level instruction measurements, **not cycle counts or timing speedups**. Memory instruction counts do not establish cache misses, stalls, or external bandwidth. Fixed-point helper counts exclude surrounding zero-point, clamp, store, and caller call instructions.

## Instruction mix

| Class | Retired | Share |
|---|---:|---:|
| load | 1,181,593,027 | 24.28% |
| store | 63,986,578 | 1.31% |
| integer_alu | 2,369,832,774 | 48.69% |
| multiply | 612,256,941 | 12.58% |
| divide_remainder | 11,171,210 | 0.23% |
| conditional_branch | 609,706,848 | 12.53% |
| jump | 18,730,992 | 0.38% |
| other | 0 | 0.00% |
| custom | 0 | 0.00% |

## Operator groups

| Group | Layers | Instructions | Inference share | Products/instruction |
|---|---:|---:|---:|---:|
| conv_1x1 | 32 | 3,289,232,864 | 67.58% | 0.10292 |
| depthwise_5x5 | 9 | 707,529,260 | 14.54% | 0.02555 |
| depthwise_3x3 | 7 | 587,537,394 | 12.07% | 0.02140 |
| stem_convolution | 1 | 246,585,264 | 5.07% | 0.04369 |
| ADD | 9 | 23,015,214 | 0.47% | 0.00000 |
| FULLY_CONNECTED | 1 | 11,578,948 | 0.24% | 0.11055 |
| QUANTIZE | 2 | 909,439 | 0.02% | 0.00000 |
| SOFTMAX | 1 | 448,805 | 0.01% | 0.00000 |
| AVERAGE_POOL_2D | 1 | 435,798 | 0.01% | 0.00000 |
| RESHAPE | 1 | 564 | 0.00% | 0.00000 |

## Hottest functions

Counts are exclusive PC attribution: callees have their own rows; per-layer totals are inclusive.

| Function | Instructions | Share |
|---|---:|---:|
| `tflite::reference_integer_ops::ConvPerChannel` | 3,378,084,408 | 69.40% |
| `tflite::reference_integer_ops::DepthwiseConvPerChannel` | 1,213,269,982 | 24.93% |
| `tflite::MultiplyByQuantizedMultiplier` | 239,535,450 | 4.92% |
| `tflite::EvalAddQuantized` | 23,007,078 | 0.47% |
| `void tflite::reference_integer_ops::FullyConnected<signed char, signed char, signed char, int>` | 11,543,100 | 0.24% |
| `tflite::EvalQuantizeReference` | 909,299 | 0.02% |
| `tflite::AverageEval` | 435,542 | 0.01% |
| `gemmlowp::FixedPoint<int, 0> gemmlowp::exp_on_negative_values<int, 5>` | 232,296 | 0.00% |
| `gemmlowp::FixedPoint<int, 0> gemmlowp::exp_on_interval_between_negative_one_quarter_and_0_excl<int>` | 117,992 | 0.00% |
| `tflite::SoftmaxEval` | 98,181 | 0.00% |

## Hottest instruction PCs

| PC | Instruction | Executions | Source |
|---|---|---:|---|
| `0x80005c94` | `lb x23,0(x17)` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:98 |
| `0x80005c98` | `lb x16,0(x14)` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:100 |
| `0x80005c9c` | `c.addi x14,1` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:94 (discriminator 1) |
| `0x80005c9e` | `addw x23,x23,x8` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:117 |
| `0x80005ca2` | `mulw x16,x16,x23` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:117 |
| `0x80005ca6` | `c.addi x17,1` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:94 (discriminator 1) |
| `0x80005ca8` | `addw x10,x16,x10` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:117 |
| `0x80005cac` | `bne x27,x14,80005c94` | 349,311,072 | tensorflow/lite/kernels/internal/reference/integer_ops/conv.h:94 (discriminator 1) |
| `0x8000745e` | `xori x13,x15,-1` | 34,532,064 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:79 |
| `0x80007462` | `srliw x13,x13,0x1f` | 34,532,064 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:79 |
| `0x80007466` | `c.beqz x13,800074bc` | 34,532,064 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:79 |
| `0x800074bc` | `c.addiw x14,1` | 34,532,064 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:73 (discriminator 2) |
| `0x800074be` | `c.addw x15,x9` | 34,532,064 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:73 (discriminator 1) |
| `0x800074c0` | `bne x8,x14,8000745e` | 34,532,064 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:73 |
| `0x80007468` | `bge x15,x19,800074bc` | 33,542,208 | tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h:79 |

## Representative layers for the next milestone

Choose the highest-instruction layer in each compute family; these are recommendations, not extracted standalone benchmarks.

| Family | Node | Input / weights / output | Instructions |
|---|---:|---|---:|
| conv_1x1 | 4 | `[[1, 112, 112, 16], [96, 1, 1, 16]] -> [[1, 112, 112, 96]]` | 327,839,821 |
| stem_convolution | 1 | `[[1, 224, 224, 3], [32, 3, 3, 3]] -> [[1, 112, 112, 32]]` | 246,585,264 |
| depthwise_3x3 | 8 | `[[1, 56, 56, 144], [1, 3, 3, 144]] -> [[1, 56, 56, 144]]` | 184,382,040 |
| depthwise_5x5 | 15 | `[[1, 28, 28, 240], [1, 5, 5, 240]] -> [[1, 28, 28, 240]]` | 162,824,238 |
| FULLY_CONNECTED | 61 | `[[1, 1280], [1000, 1280]] -> [[1, 1000]]` | 11,578,948 |

## Footprint

Debug information is non-loadable and excluded; BSS includes the reserved 2 MiB arena, not just its used portion.

- executable_code_bytes: 116,916
- model_bytes: 5,422,760
- other_readonly_bytes: 16,976
- initialized_writable_bytes: 2,936
- bss_bytes: 2,097,872

## Interpretation and reproduction

Read [analysis.md](analysis.md) for the reviewed bottleneck ranking and disassembly evidence. Run `gmake profile-tests`, then `gmake profile-spike`. Run `gmake profile-report` to regenerate reports from ignored captures. `summary.json` records provenance and per-layer results; `layers.csv` is the comparison table. See [the profiling guide](../../../docs/profiling.md) for methodology and later B1/X1/X2 comparisons.
