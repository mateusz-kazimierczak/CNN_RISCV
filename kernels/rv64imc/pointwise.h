// Software-only NHWC x OHWI 1x1 convolution. Numerical scaling is
// pinned TFLM.
#pragma once

#include "quantization_select.h"
#include <cstdint>

namespace arch_project {

// NHWC gives one contiguous input-channel vector per pixel. OHWI gives one
// contiguous weight row per output channel; a 1x1 filter has no spatial taps.
//
// Eight scalar products, in channel order. This is the reduction boundary for
// a future packed backend; B1 uses ordinary, signed INT8 loads and INT32 math.
// The compiler proves INT32 safety for bias-first accumulation and all
// prefixes.
inline int32_t dot8(int32_t accumulator, const int8_t *input,
                    const int8_t *weights) {
#pragma GCC unroll 8
  for (int lane = 0; lane < 8; ++lane)
    accumulator += static_cast<int32_t>(input[lane]) * weights[lane];
  return accumulator;
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
    const int8_t *weight_row = weights;
    for (int channel = 0; channel < OutputChannels; ++channel) {
      // corrected_bias = original_bias - input_zero_point * sum(weight_row).
      // The compiler proved that this bias and every accumulator prefix fit.
      int32_t accumulator = corrected_biases[channel];
      const int8_t *input_group = input;
      const int8_t *input_end = input_group + InputChannels;
      do {
        accumulator = dot8(accumulator, input_group, weight_row);
        input_group += 8;
        weight_row += 8;
      } while (input_group != input_end);
      accumulator = ARCH_PROJECT_MULTIPLIER(accumulator, multipliers[channel],
                                            shifts[channel]);
      accumulator += OutputOffset;
      if (accumulator < ActivationMin)
        accumulator = ActivationMin;
      if (accumulator > ActivationMax)
        accumulator = ActivationMax;
      *output++ = static_cast<int8_t>(accumulator);
    }
    input += InputChannels;
  }
}

// Keep output scheduling separate from the eight-lane reduction backend.
// B1 uses scalar loads/products; a later packed backend can consume the same
// input group and OHWI row strides without changing the surrounding
// schedule.
struct ScalarDot8Block {
  template <int Block, int InputChannels>
  static inline void accumulate(int32_t (&accumulator)[Block],
                                const int8_t *input, const int8_t *weights) {
#pragma GCC unroll 8
    for (int lane = 0; lane < 8; ++lane) {
      const int32_t input_value = input[lane];
#pragma GCC unroll 4
      for (int block_channel = 0; block_channel < Block; ++block_channel)
        accumulator[block_channel] +=
            input_value * weights[block_channel * InputChannels + lane];
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
      // Independent output channels share input loads, never accumulators.
      // Each accumulator still visits its own weight row in input order.
      int32_t accumulator[Block];
#pragma GCC unroll 4
      for (int block_channel = 0; block_channel < Block; ++block_channel)
        accumulator[block_channel] = corrected_biases[channel + block_channel];
      const int8_t *input_group = input;
      const int8_t *weight_group = weights + channel * InputChannels;
      const int8_t *input_end = input_group + InputChannels;
      do {
        Reduction::template accumulate<Block, InputChannels>(
            accumulator, input_group, weight_group);
        input_group += 8;
        weight_group += 8;
      } while (input_group != input_end);
#pragma GCC unroll 4
      for (int block_channel = 0; block_channel < Block; ++block_channel) {
        int32_t scaled_output = ARCH_PROJECT_MULTIPLIER(
            accumulator[block_channel], multipliers[channel + block_channel],
            shifts[channel + block_channel]);
        scaled_output += OutputOffset;
        if (scaled_output < ActivationMin)
          scaled_output = ActivationMin;
        if (scaled_output > ActivationMax)
          scaled_output = ActivationMax;
        *output++ = static_cast<int8_t>(scaled_output);
      }
    }
    input += InputChannels;
  }
}

} // namespace arch_project
