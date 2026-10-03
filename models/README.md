# EfficientNet-Lite0 model audit

See [the project guide](../README.md) for building/running the model and
[the runtime guide](../tflm/README.md#setup-and-inference-arithmetic) for how
TFLM uses its quantization metadata.

## Artifact

- File: `efficientnet-lite0-int8.tflite`
- Upstream archive: `https://storage.googleapis.com/cloud-tpu-checkpoints/efficientnet/lite/efficientnet-lite0.tar.gz`
- Upstream path: `efficientnet-lite0/efficientnet-lite0-int8.tflite`
- Size: 5,422,760 bytes (5.17 MiB)
- SHA-256: `31c18ecf5cfb7bddf182e450e4029834271fc70e15b5fae6ddb5995ac2a6de51`
- Format: TFLite FlatBuffer (`TFL3`), schema version 3

The artifact comes from the TensorFlow TPU EfficientNet-Lite release, not from
the similarly named EfficientNet-B0 model. EfficientNet-Lite0 removes
squeeze-and-excitation, replaces Swish with ReLU6, and has a fixed 224x224
input.

## Constraint audit

| Requirement | Observed | Result |
|---|---:|---|
| Model size, 2-12M parameters | 4,631,000 learned parameters: 4,608,992 weights + 22,008 biases | Pass |
| Compute, 0.2-2 GMAC/inference | 385,187,552 MACs counted from Conv/DepthwiseConv/FC tensor shapes; upstream reports 407M MAdds | Pass |
| INT8 weights | 50/50 operator weight tensors are signed INT8 | Pass |
| INT8 activations | All 63 internal runtime tensors are signed INT8 | Pass internally |
| Integer accumulators/biases | All 50 operator bias tensors are INT32 | Pass |
| Integer model graph | Zero FLOAT16/FLOAT32/FLOAT64 tensors and no float operators | Pass; runtime setup still uses software FP |
| Static shapes | One fixed-shape subgraph, input `[1,224,224,3]`, output `[1,1000]` | Pass |
| Strict signed-INT8 public I/O | Public input and output are UINT8 | Does not strictly pass |

The public UINT8 I/O is a compatibility shell around a signed-INT8 graph:

- Input tensor 164 (`images`): UINT8, scale `0.01256601699`, zero-point `131`.
- First internal tensor 0 (`images_int8`): INT8, the same scale, zero-point `3`.
- Final internal tensor 163 (`Softmax_int8`): INT8, scale `1/256`, zero-point `-128`.
- Output tensor 165 (`Softmax`): UINT8, scale `1/256`, zero-point `0`.

The first and last operations are `QUANTIZE` conversions with a 128-point
representation shift. For the bare-metal port, preprocess directly into tensor
0 and consume tensor 163, or retain two inexpensive boundary conversions. The
computational core itself is W8A8 with signed INT8 activations.

The current TFLM application retains both boundary conversions and reads/writes
the public UINT8 tensors. Direct internal-tensor I/O would require changing the
graph/application; it is a possible later optimization.

## Quantization details

- Every weight tensor has a symmetric zero-point of 0.
- 49 convolution/depthwise-convolution weights use per-output-channel scales.
- The final fully connected weight tensor uses one per-tensor scale.
- Every INT32 bias scale equals its input activation scale times its weight scale.
- Activations use per-tensor affine quantization.
- No sparsity metadata or custom operators are required.

Quantization scales are floating-point metadata even though weights and
activations are integers. TFLM calculates fixed-point multipliers from those
scales during `AllocateTensors()`. Our RV64IMC build performs this setup in
software using integer instructions; per-element requantization in `Invoke()`
uses integer arithmetic. This model-file audit alone cannot establish the
runtime's arithmetic or instruction-set requirements.

Operator inventory (64 total):

| Operator | Count | TFLite op version |
|---|---:|---:|
| `CONV_2D` | 33 | 3 |
| `DEPTHWISE_CONV_2D` | 16 | 3 |
| `ADD` | 9 | 2 |
| `QUANTIZE` | 2 | 1 |
| `AVERAGE_POOL_2D` | 1 | 2 |
| `RESHAPE` | 1 | 1 |
| `FULLY_CONNECTED` | 1 | 4 |
| `SOFTMAX` | 1 | 2 |

This is a favorable graph for a small bare-metal runtime: the dominant work is
33 regular convolutions (mostly 1x1), 16 depthwise convolutions, and one fully
connected layer. Requantization is fused into the quantized kernel outputs.

## Reproduce the inspection

From the repository root:

```bash
uv run --python 3.12 --with tflite --with numpy \
  python tools/inspect_tflite.py \
  models/efficientnet-lite0-int8.tflite \
  --output models/efficientnet-lite0-int8.audit.json
```
