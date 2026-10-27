# X5: packed RGB stem using the existing Xqmac8 ISA

X5 inherits X4 and replaces only the first RGB convolution (node 1). Each
3×3×3 patch is packed once into four 64-bit words, then reused for all 32 output
channels. Four Xqmac8 instructions reduce each output channel, followed by the
unchanged Xrequant descriptor and byte output. No new instruction or RTL change
is needed, and no whole-image im2col buffer is allocated.

## Layout and exact arithmetic

For each output channel, the compiler copies the original OHWI 27 weights into
a 32-byte row and zero-fills the final five lanes. The prepared payload uses
little-endian INT32 storage with eight-byte-aligned rows; the kernel reads it
through alias-safe eight-byte loads. Original constants and prepared IR remain
intact. The activation patch follows exactly the same spatial/channel order.
The kernel reads only valid input taps and zero-fills all invalid spatial lanes
and the five unused tail lanes. NHWC RGB input need not be aligned.

For input offset d=-zero_point and valid taps V, the compiler prepares:

```
corrected_bias[region][oc] = original_bias[oc] + d * sum(weights[oc][t], t in V)
accumulator = corrected_bias[region][oc] + sum(raw_signed_input[t] * weights[oc][t])
```

The region geometry is shared with the depthwise correction code. Padding taps
add neither raw input nor offset contributions. This avoids a runtime offset
addition and makes the border algebra identical to the reference. A full-filter
correction would be incorrect at the right/bottom borders. The fixed 224×224
stride-two model has four distinct valid rectangles and a 112×112 region map.

The compiler proves every possible bias-first INT32 accumulator prefix is in
range using per-weight extrema for all signed INT8 inputs. This includes the
four packed-MAC boundaries, so architectural modulo-INT32 arithmetic agrees
with mathematical accumulation. It rejects unsafe biases and geometry. Saved
kernel plans regenerate and compare all weights, regions and corrected biases.
Native sanitizer tests independently compare exact pre-requantization INT64
results for 64 cases: small/odd dimensions, all border shapes, extreme inputs
and weights, positive/negative/zero offsets, missing biases, unaligned input,
and output-channel counts beyond the fixed model.

## Work and generated code

The logical convolution still has 10,838,016 products. Its padded schedule
executes 112×112×32×32 = 12,845,056 lane products, including deliberately zero
spatial/tail lanes. The profiler distinguishes this from logical work and
requires exactly 1,605,632 Xqmac8 and 401,408 Xrequant retirements in the stem.
There are no scalar multiplications in the new stem. Other execution units keep
their original schedules and measured instruction counts.

The emitted RV64 channel loop holds all four patch words in registers and
loads four prepacked weight words, a corrected bias and a descriptor per output
channel. Activation gathering is outside that loop. This reduces stem loads
from 27,628,124 to 2,757,680 instructions. The patch occupies only 32 bytes in
source; the compiler keeps it in registers in the measured kernel.

## Results and reproduction

| Metric | X4 | X5 |
|---|---:|---:|
| Full inference instructions | 229,114,977 | 167,729,178 |
| Stem instructions | 69,472,265 | 8,086,466 |
| Executable bytes | 38,572 | 38,140 |
| Activation workspace bytes | 1,505,280 | 1,505,280 |

The stem drops 88.36%; full inference drops 26.79%. Prepared constants grow by
51,712 bytes: 50,176 for the region map, 512 for corrected biases and 1,024 for
packed weights. These are retired-instruction improvements, not cycle-speedup
claims. X5 hardware timing and cycles have not been measured.

```
make compiler-x5-checkpoint
```

The checkpoint builds native, tensor-capture, ASan/UBSan and RV64 binaries;
compares all eight reference cases; checks baseline and random_42 full RV64
outputs; replays the stem and five control layers on all eight cases; verifies
repeated profiles; runs the complete compiler/profiler regressions; and rebuilds
B1/X1/X2/X3/X4 to compare every allocated byte and load segment. Existing ISA
libraries must retain the exact X4 identities. Individual targets are
`compiler-x5-verify`, `compiler-x5-tests`, `compiler-x5-controls`,
`compiler-x5-regressions`, `compiler-x5-profile` and `compiler-x5-replay`.

See [validated checkpoint](../results/profiling/X5-verification.md),
[full profile](../results/profiling/X5/README.md), and
[layer replay](../results/profiling/X5-replay/README.md).
