// Static operator subsets; reference-compatible integer arithmetic. See NOTICE.
#pragma once
#include "quantization.h"
#include <cstdint>
#include <limits>
namespace arch_project {

// Layout notation used here and in the generated calls:
//   NHWC = batch, height, width, channels (activations).
//   OHWI = output channel, filter height, filter width, input channel
//   (weights).
// InputOffset is -input_zero_point; OutputOffset is output_zero_point.
// Dimensions, offsets, multipliers and shifts are compile-time template values.
// Only tensor contents and per-channel parameter arrays are read at runtime.

// RGB stem: each output channel is a 3x3x3 dot product. The footprint may
// cross the input border; skipped taps represent real zero, so neither the
// sample nor its input offset contributes there. Bias follows the reduction.
template <int InputHeight, int InputWidth, int OutputChannels, int OutputHeight,
          int OutputWidth, int PaddingTop, int PaddingLeft, int InputOffset,
          int OutputOffset, int ActivationMin, int ActivationMax,
          class Requantization = numeric::GenericRequantization>
__attribute__((always_inline)) inline void
stem_rgb(const int8_t *input, const int8_t *weights, const int32_t *bias,
         const int32_t *multipliers, const int32_t *shifts, int8_t *output) {
  for (int output_y = 0; output_y < OutputHeight; ++output_y)
    for (int output_x = 0; output_x < OutputWidth; ++output_x) {
      const int origin_y = output_y * 2 - PaddingTop,
                origin_x = output_x * 2 - PaddingLeft;
      for (int output_channel = 0; output_channel < OutputChannels;
           ++output_channel) {
        int32_t accumulator = 0;
        for (int filter_y = 0; filter_y < 3; ++filter_y) {
          const int input_y = origin_y + filter_y;
          if (input_y < 0 || input_y >= InputHeight)
            continue;
          for (int filter_x = 0; filter_x < 3; ++filter_x) {
            const int input_x = origin_x + filter_x;
            if (input_x < 0 || input_x >= InputWidth)
              continue;
            const int8_t *input_pixel =
                input + (input_y * InputWidth + input_x) * 3;
            const int8_t *filter_pixel =
                weights + output_channel * 27 + (filter_y * 3 + filter_x) * 3;
#pragma GCC unroll 3
            for (int input_channel = 0; input_channel < 3; ++input_channel)
              accumulator += (static_cast<int32_t>(input_pixel[input_channel]) +
                              InputOffset) *
                             filter_pixel[input_channel];
          }
        }
        if (bias)
          accumulator += bias[output_channel];
        *output++ = static_cast<int8_t>(numeric::clamp(
            Requantization::apply(accumulator, multipliers[output_channel],
                                  shifts[output_channel]) +
                OutputOffset,
            ActivationMin, ActivationMax));
      }
    }
}

// Fully connected: one weight row per output channel, shared by each batch.
// Keep the input offset inside each product; this path uses original biases.
template <int Batches, int InputChannels, int OutputChannels, int InputOffset,
          int OutputOffset, int OutputMultiplier, int OutputShift,
          int ActivationMin, int ActivationMax>
inline void fully_connected(const int8_t *input, const int8_t *weights,
                            const int32_t *bias, int8_t *output) {
  for (int batch = 0; batch < Batches; ++batch) {
    for (int output_channel = 0; output_channel < OutputChannels;
         ++output_channel) {
      int32_t accumulator = 0;
      const int8_t *weight_row = weights + output_channel * InputChannels;
      int input_channel = 0;
      // Same eight-product grouping as the convolution reduction, with the
      // input offset retained here. No new corrected-bias payload is needed.
      for (; input_channel + 8 <= InputChannels; input_channel += 8) {
#pragma GCC unroll 8
        for (int lane = 0; lane < 8; ++lane)
          accumulator += (static_cast<int32_t>(input[input_channel + lane]) +
                          InputOffset) *
                         weight_row[input_channel + lane];
      }
      for (; input_channel < InputChannels; ++input_channel)
        accumulator +=
            (static_cast<int32_t>(input[input_channel]) + InputOffset) *
            weight_row[input_channel];
      if (bias)
        accumulator += bias[output_channel];
      *output++ = static_cast<int8_t>(numeric::clamp(
          numeric::multiply(accumulator, OutputMultiplier, OutputShift) +
              OutputOffset,
          ActivationMin, ActivationMax));
    }
    input += InputChannels;
  }
}

// Residual ADD: the operands can have different zero points and scales.
// Scale them independently into a common domain, add, then scale and clamp
// once to the output domain. The shifts below are nonpositive right shifts.
template <int ElementCount, int LhsOffset, int RhsOffset, int OutputOffset,
          int LhsMultiplier, int RhsMultiplier, int OutputMultiplier,
          int LhsShift, int RhsShift, int OutputShift, int LeftShift,
          int ActivationMin, int ActivationMax>
inline void add(const int8_t *lhs, const int8_t *rhs, int8_t *output) {
  static_assert(LhsShift <= 0 && RhsShift <= 0 && OutputShift <= 0);
  for (int i = 0; i < ElementCount; ++i) {
    const int32_t scaled_lhs = numeric::smaller(
        (lhs[i] + LhsOffset) * (1 << LeftShift), LhsMultiplier, LhsShift);
    const int32_t scaled_rhs = numeric::smaller(
        (rhs[i] + RhsOffset) * (1 << LeftShift), RhsMultiplier, RhsShift);
    output[i] = static_cast<int8_t>(
        numeric::clamp(numeric::smaller(scaled_lhs + scaled_rhs,
                                        OutputMultiplier, OutputShift) +
                           OutputOffset,
                       ActivationMin, ActivationMax));
  }
}

// Global average pool: NHWC channel stride is Channels. Accumulate signed
// samples without zero-point adjustment because input/output quantization
// is identical for this validated operator subset.
template <int Batches, int Pixels, int Channels, int ActivationMin,
          int ActivationMax>
inline void global_average(const int8_t *input, int8_t *output) {
  static_assert(Pixels > 0 && Pixels <= INT32_MAX / 129);
  for (int batch = 0; batch < Batches; ++batch) {
    for (int output_channel = 0; output_channel < Channels; ++output_channel) {
      int32_t sum = 0;
      for (int pixel = 0; pixel < Pixels; ++pixel)
        sum += input[pixel * Channels + output_channel];
      // C++ division truncates toward zero; reference rounding is away from
      // zero at a half, with count/2 truncated before adding/subtracting.
      const int32_t average =
          (sum > 0 ? sum + Pixels / 2 : sum - Pixels / 2) / Pixels;
      *output++ = static_cast<int8_t>(
          numeric::clamp(average, ActivationMin, ActivationMax));
    }
    input += Pixels * Channels;
  }
}

// Public UINT8 <-> internal INT8 conversion. Equal scales and a zero-point
// difference of 128 allow an exact sign-bit flip; other prepared scales use
// the same double-rounding helper as the convolution output path.
template <class Input, class Output, int ElementCount, int OutputMultiplier,
          int OutputShift, int InputZeroPoint, int OutputZeroPoint>
inline void boundary(const Input *input, Output *output) {
  if constexpr (OutputMultiplier == (1 << 30) && OutputShift == 1 &&
                ((std::numeric_limits<Input>::min() == -128 &&
                  InputZeroPoint - OutputZeroPoint == -128) ||
                 (std::numeric_limits<Input>::min() == 0 &&
                  InputZeroPoint - OutputZeroPoint == 128))) {
    for (int i = 0; i < ElementCount; ++i)
      output[i] = static_cast<Output>(input[i] ^ 0x80);
  } else {
    for (int i = 0; i < ElementCount; ++i)
      output[i] = static_cast<Output>(numeric::clamp(
          numeric::multiply(static_cast<int32_t>(input[i]) - InputZeroPoint,
                            OutputMultiplier, OutputShift) +
              OutputZeroPoint,
          std::numeric_limits<Output>::min(),
          std::numeric_limits<Output>::max()));
  }
}
} // namespace arch_project
