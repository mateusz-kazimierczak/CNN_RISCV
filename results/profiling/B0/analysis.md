# B0 findings and optimization priorities

These conclusions use the two identical captures summarized in
[README.md](README.md), with machine-readable evidence in
[summary.json](summary.json) and [layers.csv](layers.csv). PCs below identify the
measured ELF, whose hash is in the report; they are not hardcoded collector gates.
This is **instruction-expansion analysis**, not a claim about CV-Wally stalls,
cache misses, multiply latency, or cycle speedup.

## Three largest measured execution costs

The following are the three largest **exclusive function-body** counts. Shared
scaling helpers have their own row rather than being counted again in convolution.
Together these bodies contribute about 99.25% of inference instructions.

| Rank | Cost | Retired instructions | Inference share | Architectural opportunity |
|---|---|---:|---:|---|
| 1 | Scalar reference convolution | 3,378,084,408 | 69.40% | Packed loads/MACs and amortized loop bookkeeping; specialize the common 1×1 path |
| 2 | Generic depthwise convolution | 1,213,269,982 | 24.93% | Hoist shape/address work, separate interior/border handling, investigate depthwise-appropriate data access |
| 3 | Fixed-point scaling helper | 239,535,450 | 4.92% | Bit-exact rounding/shift instruction, evaluated after MAC/software improvements |

The highest-cost **operator families**, counting their helpers inclusively, are
1×1 convolution (3,289,232,864 instructions; 67.58%), 5×5 depthwise
(707,529,260; 14.54%), and 3×3 depthwise (587,537,394; 12.07%). Ordinary
convolution and depthwise together account for 99.25% of callback work relative
to total inference, including the 3×3 stem and scaling helpers. The interpreter
itself contributes only 4,820 instructions: optimizing dispatch is not a priority.

## 1. Scalar convolution: arithmetic is only part of the inner loop

The eight hottest PCs, `0x80005c94` through `0x80005cac`, each execute
349,311,072 times. They form the complete channel-reduction loop in the measured
`ConvPerChannel` body:

| Work per product | Instructions | Total retirements | Inference share |
|---|---:|---:|---:|
| Activation and weight byte loads | 2 | 698,622,144 | 14.35% |
| Input-zero-point adjustment, multiply, accumulation | 3 | 1,047,933,216 | 21.53% |
| Two pointer increments and loop branch | 3 | 1,047,933,216 | 21.53% |
| Entire loop | 8 | 2,794,488,576 | 57.41% |

The scalar product is `mulw` at `0x80005ca2`; `addw` at `0x80005ca8`
accumulates it. The loop also handles the input offset (`0x80005c9e`), which
must not disappear when designing a packed INT8 implementation.

This directly supports packed arithmetic **and** wider/packed operand loads and
loop amortization. Replacing only the multiply, while retaining scalar operand
loading and control, leaves most of this loop's instruction work intact. The
1×1 callbacks average 9.716 instructions/executed product; the extra work beyond
this eight-instruction loop includes output handling, scaling, and generic
convolution setup/bounds/address logic. Specializing 1×1 is a well-motivated B1
experiment, not an optimization already applied to B0.

## 2. Depthwise: indexing overhead is disproportionately expensive

Depthwise performs 30,648,416 executed products (8.04% of the model's executed
products), but consumes 1,295,066,654 inclusive instructions (26.61% of inference).
The 3×3 and 5×5 families average **46.739** and **39.138** instructions/product,
respectively, versus 9.716 for 1×1 convolution.

Disassembly explains part of the difference. Before the scalar MAC at
`0x800074b6`, the generic depthwise loop reloads shape dimensions and performs
five separate address-index multiplications at `0x8000747a`, `0x80007486`,
`0x8000748e`, `0x80007494`, and `0x8000749a`. Each runs once per valid product:
**153,242,080 address-multiply instructions**, separate from the 30,648,416 MAC
multiplies. It also performs padding checks at each candidate spatial position.

Next experiments should test hoisted pointer/stride calculations and an interior
path without repeated border checks. Do not assume a dense packed dot-product
instruction automatically fits depthwise: neighboring NHWC channels belong to
different output accumulators, while spatial taps have strided inputs. Any packing
or layout changes require their own overhead measurements and correctness tests.

## 3. Scaling: real but not the first whole-model lever

`MultiplyByQuantizedMultiplier(int, int, int)` contributes **239,535,450** body
instructions, or 4.92% of inference. This is a measured fixed-point scaling cost,
not the entire requantization sequence: caller calls, surrounding zero-point
addition, clamps, and stores remain in the kernels. Inlined scaling in elementwise
code is also not assigned to this out-of-line helper row.

Even hypothetically deleting the entire measured helper would reduce instructions
by only 4.92% (instruction-count ratio about 1.052×), not 1.5×. A requantization
instruction is still an assignment requirement and may matter more after MAC and
loop optimization. Preserve the current rounding and saturation behavior and
measure it incrementally after X1; do not claim that the standalone 4.92% share
predicts hardware timing.

## Other checks and caveats

- **Memory instructions:** 1,245,579,605 loads/stores, 25.59% of inference and
  3.267 per executed product. These include operands, metadata, spills, and
  output handling. They do not establish external-memory bandwidth or stalls.
- **Multiply instructions are not all MACs:** 612,256,941 multiplies retire;
  only 381,239,488 are the reference kernels' scalar products. The remaining
  231,017,453 include indexing and fixed-point arithmetic. The three MAC sites
  independently confirm the padding-aware count: convolution `0x80005ca2`
  executes 349,311,072 times; depthwise `0x800074b6` 30,648,416 times; fully
  connected `0x80008a2a` 1,280,000 times. Their sum is 381,239,488.
- **Setup is separate:** `AllocateTensors()` takes 14,532,148 instructions;
  software double multiply/divide helpers are its largest contributors. This
  must not be mixed into integer inference or described as FP hardware use.
- **Small operator work:** FC is only 0.24% and ADD 0.47% of inference. FC is
  useful for initial kernel verification, but optimizing it alone cannot
  materially accelerate this complete model.

## Next milestone: representative kernels, then incremental optimization

Start with node **4**, the highest-instruction 1×1 layer:
`[1,112,112,16] × [96,1,1,16] → [1,112,112,96]` (327,839,821 instructions).
Also test node **58**, with input depth 320, to avoid tuning only for a short
dot product. Use node **8** for 3×3 depthwise (184,382,040 instructions), node
**15** for 5×5 depthwise (162,824,238), and node **61** for FC correctness.
Node **1** is the stem/border case with input depth 3.

For each extracted kernel, retain quantization parameters, input offsets,
padding, and activation clamps; compare bit-exact outputs with B0. Measure B1
software changes first, X1 packed-MAC changes next, and X2 requantization last,
keeping full-model results as the final check. Extraction, optimization, ISA
semantics, cache simulation, and RTL cycle/area work are deliberately not part
of this completed profiling milestone.
