// Generated fixed execution order. Kernel algorithms come from pinned TFLM.
#include "model.h"
#include "constants.h"
#include "numerics.h"
#include <cstring>
#include "tensorflow/lite/kernels/internal/reference/integer_ops/conv.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/fully_connected.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/add.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/pooling.h"
#include "tensorflow/lite/kernels/internal/reference/requantize.h"

#define A0_NOINLINE __attribute__((noinline))
// Keeps even the no-op Reshape's stable node wrapper observable. No target
// instruction is added by this compiler barrier; call/return overhead remains.
#define A0_NODE_ENTRY() asm volatile("" ::: "memory")
// Explicit assignments preserve static dimensions under the bare-metal
// -fno-builtin flags. RuntimeShape(rank, dims) uses an opaque memcpy there.
template<int N>
static inline tflite::RuntimeShape a0_static_shape(const int32_t (&dims)[N]) {
  tflite::RuntimeShape shape(N);
  for (int i = 0; i < N; ++i) shape.SetDim(i, dims[i]);
  return shape;
}
static_assert((-3 >> 1) == -2, "Pinned helpers require arithmetic right shifts");
