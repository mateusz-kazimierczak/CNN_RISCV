#pragma once
// Only the generated translation unit chooses this backend. The pinned oracle
// never includes this adapter and remains an independent numerical reference.
#if defined(ARCH_PROJECT_PROJECT_NUMERICS)
#include "kernels/project/quantization.h"
#define ARCH_PROJECT_MULTIPLIER arch_project::numeric::multiply
#else
#include "tensorflow/lite/kernels/internal/common.h"
#define ARCH_PROJECT_MULTIPLIER tflite::MultiplyByQuantizedMultiplier
#endif

namespace arch_project {
struct DefaultRequantization {
  static constexpr bool packed_output = false;
  static inline int32_t apply(int32_t x, int32_t multiplier, int shift) {
    return ARCH_PROJECT_MULTIPLIER(x, multiplier, shift);
  }
};
} // namespace arch_project
