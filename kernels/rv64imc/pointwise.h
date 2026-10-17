// Software-only NHWC x OHWI 1x1 convolution. Numerical scaling is pinned TFLM.
#pragma once

#include "quantization_select.h"
#include <cstdint>

namespace arch_project {

// Eight scalar products, in channel order. This is the reduction boundary for
// a future packed backend; B1 uses ordinary, signed INT8 loads and INT32 math.
// The compiler proves INT32 safety for bias-first accumulation and all
// prefixes.
inline int32_t dot8(int32_t acc, const int8_t *input, const int8_t *weights) {
#pragma GCC unroll 8
  for (int lane = 0; lane < 8; ++lane)
    acc += static_cast<int32_t>(input[lane]) * weights[lane];
  return acc;
}

template <int Pixels, int InputChannels, int OutputChannels, int OutputOffset,
          int ActivationMin, int ActivationMax>
inline void pointwise_dot8(const int8_t *input, const int8_t *weights,
                           const int32_t *corrected_biases,
                           const int32_t *multipliers, const int32_t *shifts,
                           int8_t *output) {
  static_assert(Pixels > 0 && InputChannels > 0 && OutputChannels > 0);
  static_assert(InputChannels % 8 == 0,
                "dot8 requires complete eight-lane groups");
  static_assert(ActivationMin >= -128 && ActivationMax <= 127 &&
                ActivationMin <= ActivationMax);
  for (int pixel = 0; pixel < Pixels; ++pixel) {
    const int8_t *row = weights;
    for (int channel = 0; channel < OutputChannels; ++channel) {
      int32_t acc = corrected_biases[channel];
      const int8_t *x = input;
      const int8_t *end = x + InputChannels;
      do {
        acc = dot8(acc, x, row);
        x += 8;
        row += 8;
      } while (x != end);
      acc = ARCH_PROJECT_MULTIPLIER(acc, multipliers[channel],
                                                  shifts[channel]);
      acc += OutputOffset;
      if (acc < ActivationMin)
        acc = ActivationMin;
      if (acc > ActivationMax)
        acc = ActivationMax;
      *output++ = static_cast<int8_t>(acc);
    }
    input += InputChannels;
  }
}

// Keep output scheduling separate from the eight-lane reduction backend.
// B1 uses scalar loads/products; a later packed backend can consume the same
// input group and OHWI row strides without changing the surrounding schedule.
struct ScalarDot8Block {
  template <int Block, int InputChannels>
  static inline void accumulate(int32_t (&acc)[Block], const int8_t *input,
                                const int8_t *weights) {
#pragma GCC unroll 8
    for (int lane = 0; lane < 8; ++lane) {
      const int32_t x = input[lane];
#pragma GCC unroll 4
      for (int channel = 0; channel < Block; ++channel)
        acc[channel] += x * weights[channel * InputChannels + lane];
    }
  }
};

template <int Pixels, int InputChannels, int OutputChannels, int OutputOffset,
          int ActivationMin, int ActivationMax, int Block,
          class Reduction = ScalarDot8Block>
inline void pointwise_dot8_blocked(const int8_t *input, const int8_t *weights,
                                   const int32_t *corrected_biases,
                                   const int32_t *multipliers,
                                   const int32_t *shifts, int8_t *output) {
  static_assert(Block == 2 || Block == 4);
  static_assert(Pixels > 0 && InputChannels > 0 && OutputChannels > 0);
  static_assert(InputChannels % 8 == 0 && OutputChannels % Block == 0);
  static_assert(ActivationMin >= -128 && ActivationMax <= 127 &&
                ActivationMin <= ActivationMax);
  for (int pixel = 0; pixel < Pixels; ++pixel) {
    for (int channel = 0; channel < OutputChannels; channel += Block) {
      int32_t acc[Block];
#pragma GCC unroll 4
      for (int c = 0; c < Block; ++c)
        acc[c] = corrected_biases[channel + c];
      const int8_t *x = input;
      const int8_t *w = weights + channel * InputChannels;
      const int8_t *end = x + InputChannels;
      do {
        Reduction::template accumulate<Block, InputChannels>(acc, x, w);
        x += 8;
        w += 8;
      } while (x != end);
#pragma GCC unroll 4
      for (int c = 0; c < Block; ++c) {
        int32_t value = ARCH_PROJECT_MULTIPLIER(
            acc[c], multipliers[channel + c], shifts[channel + c]);
        value += OutputOffset;
        if (value < ActivationMin)
          value = ActivationMin;
        if (value > ActivationMax)
          value = ActivationMax;
        *output++ = static_cast<int8_t>(value);
      }
    }
    input += InputChannels;
  }
}

} // namespace arch_project
