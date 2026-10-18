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

struct ScalarDot8Single {
  using Accumulator = int32_t;
  static inline int32_t apply(int32_t accumulator, const int8_t* input,
                             const int8_t* weights) {
    return dot8(accumulator, input, weights);
  }
};

template <int Pixels, int InputChannels, int OutputChannels, int OutputOffset,
          int ActivationMin, int ActivationMax,
          class Requantization = DefaultRequantization,
          class Reduction = ScalarDot8Single>
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
      typename Reduction::Accumulator accumulator = corrected_biases[channel];
      const int8_t *input_group = input;
      const int8_t *input_end = input_group + InputChannels;
      do {
        accumulator = Reduction::apply(accumulator, input_group, weight_row);
        input_group += 8;
        weight_row += 8;
      } while (input_group != input_end);
      if constexpr (Requantization::packed_output) {
        *output++ = static_cast<int8_t>(Requantization::finish(accumulator, Requantization::load(multipliers, channel)));
      } else {
      int32_t scaled_output = Requantization::apply(static_cast<int32_t>(accumulator), multipliers[channel],
                                          shifts[channel]);
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

// Keep output scheduling separate from the eight-lane reduction backend.
// B1 uses scalar loads/products; a later packed backend can consume the same
// input group and OHWI row strides without changing the surrounding
// schedule.
struct ScalarDot8Block {
  using Accumulator = int32_t;
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
          class Reduction = ScalarDot8Block,
          class Requantization = DefaultRequantization>
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
      typename Reduction::Accumulator accumulator[Block];
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
        if constexpr (Requantization::packed_output) {
          *output++ = static_cast<int8_t>(Requantization::finish(accumulator[block_channel], Requantization::load(multipliers, channel + block_channel)));
        } else {
        int32_t scaled_output = Requantization::apply(
            static_cast<int32_t>(accumulator[block_channel]), multipliers[channel + block_channel],
            shifts[channel + block_channel]);
        scaled_output += OutputOffset;
        if (scaled_output < ActivationMin)
          scaled_output = ActivationMin;
        if (scaled_output > ActivationMax)
          scaled_output = ActivationMax;
        *output++ = static_cast<int8_t>(scaled_output);
        }
      }
    }
    input += InputChannels;
  }
}

// Two NHWC pixels share the same OHWI weights. Each input is reused across
// Block output channels, and each weight across both pixels. All accumulators
// remain independent and visit input channels in their original order.
struct ScalarDot8SpatialBlock {
  using Accumulator = int32_t;
  using SinglePixel = ScalarDot8Block;
  template <int Block, int InputChannels>
  static inline void accumulate(int32_t (&accumulator)[2][Block],
                                const int8_t *input, const int8_t *weights) {
#pragma GCC unroll 8
    for (int lane = 0; lane < 8; ++lane) {
      const int32_t first_input = input[lane];
      const int32_t second_input = input[InputChannels + lane];
#pragma GCC unroll 4
      for (int channel = 0; channel < Block; ++channel) {
        const int32_t weight = weights[channel * InputChannels + lane];
        accumulator[0][channel] += first_input * weight;
        accumulator[1][channel] += second_input * weight;
      }
    }
  }
};

template <int Pixels, int InputChannels, int OutputChannels, int OutputOffset,
          int ActivationMin, int ActivationMax, int Block,
          class Reduction = ScalarDot8SpatialBlock,
          class Requantization = DefaultRequantization>
inline void pointwise_dot8_spatial2(const int8_t *input, const int8_t *weights,
                                    const int32_t *corrected_biases,
                                    const int32_t *multipliers,
                                    const int32_t *shifts, int8_t *output) {
  static_assert(Block == 2 || Block == 4);
  static_assert(Pixels > 0 && InputChannels > 0 && OutputChannels > 0);
  static_assert(InputChannels % 8 == 0 && OutputChannels % Block == 0);
  static_assert(static_cast<int64_t>(Pixels) * InputChannels <= INT32_MAX &&
                static_cast<int64_t>(Pixels) * OutputChannels <= INT32_MAX,
                "flattened pixel offsets must fit the scalar index type");
  static_assert(ActivationMin >= -128 && ActivationMax <= 127 &&
                ActivationMin <= ActivationMax);
  // Flattening batch/height/width is safe for an unpadded, stride-one 1x1
  // convolution: every pixel has the same independent dot-product schedule.
  for (int pixel = 0; pixel < (Pixels / 2) * 2; pixel += 2) {
    const int8_t *pixel_input = input + pixel * InputChannels;
    for (int channel = 0; channel < OutputChannels; channel += Block) {
      typename Reduction::Accumulator accumulator[2][Block];
#pragma GCC unroll 4
      for (int j = 0; j < Block; ++j) {
        const int32_t bias = corrected_biases[channel + j];
        accumulator[0][j] = bias;
        accumulator[1][j] = bias;
      }
      const int8_t *input_group = pixel_input;
      const int8_t *weight_group = weights + channel * InputChannels;
      const int8_t *input_end = pixel_input + InputChannels;
      do {
        Reduction::template accumulate<Block, InputChannels>(
            accumulator, input_group, weight_group);
        input_group += 8;
        weight_group += 8;
      } while (input_group != input_end);
      int8_t *first_output = output + pixel * OutputChannels + channel;
      int8_t *second_output = first_output + OutputChannels;
#pragma GCC unroll 4
      for (int j = 0; j < Block; ++j) {
        if constexpr (Requantization::packed_output) {
          const uint64_t descriptor = Requantization::load(multipliers, channel + j);
          first_output[j] = static_cast<int8_t>(Requantization::finish(accumulator[0][j], descriptor));
          second_output[j] = static_cast<int8_t>(Requantization::finish(accumulator[1][j], descriptor));
        } else {
        // Reuse channel parameters, but round/clamp each pixel separately.
        const int32_t multiplier = multipliers[channel + j];
        const int shift = shifts[channel + j];
        int32_t first = Requantization::apply(static_cast<int32_t>(accumulator[0][j]), multiplier, shift);
        int32_t second = Requantization::apply(static_cast<int32_t>(accumulator[1][j]), multiplier, shift);
        first += OutputOffset;
        second += OutputOffset;
        first = first < ActivationMin ? ActivationMin : first;
        first = first > ActivationMax ? ActivationMax : first;
        second = second < ActivationMin ? ActivationMin : second;
        second = second > ActivationMax ? ActivationMax : second;
        first_output[j] = static_cast<int8_t>(first);
        second_output[j] = static_cast<int8_t>(second);
        }
      }
    }
  }
  // Do not read a fictitious second pixel for odd spatial sizes (e.g. 7x7).
  // The same prepared biases and scaling policy apply to this one-pixel tail.
  if constexpr (Pixels % 2 != 0)
    pointwise_dot8_blocked<1, InputChannels, OutputChannels, OutputOffset,
                           ActivationMin, ActivationMax, Block, typename Reduction::SinglePixel,
                           Requantization>(
        input + (Pixels - 1) * InputChannels, weights, corrected_biases,
        multipliers, shifts, output + (Pixels - 1) * OutputChannels);
}

} // namespace arch_project
