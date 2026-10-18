// NHWC x 1HWO scalar depthwise convolution; depth multiplier and
// dilation 1. Quantization and row-major accumulation order match the pinned
// reference.
#pragma once

#include "kernels/rv64imc/quantization_select.h"
#include <cstdint>
#include "kernels/xpostinc/memory.h"

namespace arch_project {

// NHWC activations and 1HWO weights: each channel has an independent spatial
// filter. Consecutive filter taps are Channels bytes apart in the weights;
// consecutive input pixels are Channels bytes apart in the input.
// Unlike pointwise dot8, adjacent channels must not be summed together.

// Static geometry keeps address strides constant. Interior taps are unrolled;
// border bounds are clipped once per pixel, outside the channel loop. Invalid
// taps contribute nothing (including input offset), as in the reference.
template <int Batches, int InputHeight, int InputWidth, int Channels,
          int OutputHeight, int OutputWidth, int FilterSize, int StrideHeight,
          int StrideWidth, int PaddingTop, int PaddingLeft, int InputOffset,
          int OutputOffset, int ActivationMin, int ActivationMax,
          class Requantization = DefaultRequantization, bool OutlinePixel = false, bool PostIncrement = false, bool CorrectedBiases = false>
struct DepthwiseCorrected {
  static_assert(FilterSize == 3 || FilterSize == 5);
  static_assert(Batches > 0 && InputHeight > 0 && InputWidth > 0 &&
                Channels > 0 && OutputHeight > 0 && OutputWidth > 0);
  static_assert((StrideHeight == 1 || StrideHeight == 2) &&
                (StrideWidth == 1 || StrideWidth == 2));
  static_assert(PaddingTop >= 0 && PaddingLeft >= 0);
  static_assert(ActivationMin >= -128 && ActivationMax <= 127 &&
                ActivationMin <= ActivationMax);
  static constexpr int clamp(int coordinate, int limit) {
    return coordinate < 0 ? 0 : coordinate > limit ? limit : coordinate;
  }
  // Half-open output-coordinate rectangle whose entire filter is in bounds.
  // These bounds are resolved at compile time, not searched per pixel.
  static constexpr int interior_y_begin =
      clamp((PaddingTop + StrideHeight - 1) / StrideHeight, OutputHeight);
  static constexpr int interior_x_begin =
      clamp((PaddingLeft + StrideWidth - 1) / StrideWidth, OutputWidth);
  // No interior when the input is smaller than the filter. Avoid truncation
  // toward zero for the negative numerator in that case.
  static constexpr int interior_y_end =
      InputHeight < FilterSize
          ? interior_y_begin
          : clamp((InputHeight + PaddingTop - FilterSize) / StrideHeight + 1,
                  OutputHeight);
  static constexpr int interior_x_end =
      InputWidth < FilterSize
          ? interior_x_begin
          : clamp((InputWidth + PaddingLeft - FilterSize) / StrideWidth + 1,
                  OutputWidth);

  // Interior is a compile-time choice. The interior specialization has fixed
  // tap offsets; the border specialization clips once before the channel loop.
  template <bool Interior>
  static inline void pixel(const int8_t *input, const int8_t *weights,
                           const int32_t *biases, const int32_t *multipliers,
                           const int32_t *shifts, int output_y, int output_x,
                           int8_t *output, const int32_t *regions = nullptr) {
    const int origin_y = output_y * StrideHeight - PaddingTop;
    const int origin_x = output_x * StrideWidth - PaddingLeft;
    const int filter_y_begin = origin_y < 0 ? -origin_y : 0;
    const int filter_x_begin = origin_x < 0 ? -origin_x : 0;
    const int filter_y_end = origin_y + FilterSize > InputHeight
                                 ? InputHeight - origin_y
                                 : FilterSize;
    const int filter_x_end =
        origin_x + FilterSize > InputWidth ? InputWidth - origin_x : FilterSize;
    if constexpr (CorrectedBiases) biases += regions[output_y * OutputWidth + output_x] * Channels;
    for (int channel = 0; channel < Channels; ++channel) {
      int32_t accumulator = CorrectedBiases ? biases[channel] : 0;
      if constexpr (Interior) {
        const int8_t *input_origin =
            input + (origin_y * InputWidth + origin_x) * Channels + channel;
        const int8_t *channel_weights = weights + channel;
#pragma GCC unroll 5
        for (int filter_y = 0; filter_y < FilterSize; ++filter_y) {
#pragma GCC unroll 5
          for (int filter_x = 0; filter_x < FilterSize; ++filter_x)
            accumulator +=
                (static_cast<int32_t>(
                     input_origin[(filter_y * InputWidth + filter_x) *
                                  Channels]) +
                 InputOffset) *
                channel_weights[(filter_y * FilterSize + filter_x) * Channels];
        }
      } else if constexpr (PostIncrement) {
        // Form pointers only for valid taps; final updates use integer addresses.
        for (int fy = filter_y_begin; fy < filter_y_end; ++fy) {
          const int8_t* a = input + (((origin_y + fy) * InputWidth + origin_x + filter_x_begin) * Channels + channel);
          const int8_t* w = weights + (fy * FilterSize + filter_x_begin) * Channels + channel;
          for (int fx = filter_x_begin; fx < filter_x_end; ++fx) {
            const int32_t value = postinc::load<int8_t, Channels>(a);
            const int32_t weight = postinc::load<int8_t, Channels>(w);
            accumulator += (value + InputOffset) * weight;
          }
        }
      } else {
        // Construct pointers only for valid rows/taps; never form a pointer
        // before the input object, even when the origin is negative.
        for (int filter_y = filter_y_begin; filter_y < filter_y_end;
             ++filter_y) {
          for (int filter_x = filter_x_begin; filter_x < filter_x_end;
               ++filter_x)
            accumulator +=
                (static_cast<int32_t>(
                     input[((origin_y + filter_y) * InputWidth + origin_x +
                            filter_x) *
                               Channels +
                           channel]) +
                 InputOffset) *
                weights[(filter_y * FilterSize + filter_x) * Channels +
                        channel];
        }
      }
      // InputOffset is applied only to valid taps above. Adding a full-filter
      // corrected bias here would be wrong at borders.
      if (!CorrectedBiases && biases)
        accumulator += biases[channel];
      if constexpr (Requantization::packed_output) {
        const int8_t value = static_cast<int8_t>(Requantization::finish(accumulator, Requantization::load(multipliers, channel)));
        if constexpr (PostIncrement) postinc::store<int8_t, 1>(output, value);
        else output[channel] = value;
      } else {
      accumulator = Requantization::apply(accumulator, multipliers[channel],
                                          shifts[channel]);
      accumulator += OutputOffset;
      if (accumulator < ActivationMin)
        accumulator = ActivationMin;
      if (accumulator > ActivationMax)
        accumulator = ActivationMax;
      output[channel] = static_cast<int8_t>(accumulator);
      }
    }
  }

  // Keep the original pixel implementation for legacy/default code generation.
  // flatten ensures its reduction is inside this function; only the spatial
  // caller is separated, shortening the live ranges around the tap loops.
  template <bool Interior>
  __attribute__((noinline, flatten)) static void pixel_outlined(
      const int8_t *input, const int8_t *weights, const int32_t *biases,
      const int32_t *multipliers, const int32_t *shifts, int y, int x,
      int8_t *output, const int32_t *regions = nullptr) {
    pixel<Interior>(input, weights, biases, multipliers, shifts, y, x, output, regions);
  }

  template <bool Interior>
  __attribute__((always_inline)) static inline void pixel_selected(
      const int8_t *input, const int8_t *weights, const int32_t *biases,
      const int32_t *multipliers, const int32_t *shifts, int y, int x,
      int8_t *output, const int32_t *regions = nullptr) {
    if constexpr (OutlinePixel)
      pixel_outlined<Interior>(input, weights, biases, multipliers, shifts, y, x, output, regions);
    else
      pixel<Interior>(input, weights, biases, multipliers, shifts, y, x, output, regions);
  }

  static inline void run(const int8_t *input, const int8_t *weights,
                         const int32_t *biases, const int32_t *multipliers,
                         const int32_t *shifts, int8_t *output, const int32_t *regions = nullptr) {
    for (int batch = 0; batch < Batches; ++batch) {
      for (int output_y = 0; output_y < OutputHeight; ++output_y) {
        if (output_y >= interior_y_begin && output_y < interior_y_end) {
          for (int output_x = 0; output_x < interior_x_begin; ++output_x) {
            pixel_selected<false>(input, weights, biases, multipliers, shifts, output_y,
                         output_x, output, regions);
            output += Channels;
          }
          for (int output_x = interior_x_begin; output_x < interior_x_end;
               ++output_x) {
            pixel_selected<true>(input, weights, biases, multipliers, shifts, output_y,
                        output_x, output, regions);
            output += Channels;
          }
          for (int output_x = interior_x_end; output_x < OutputWidth;
               ++output_x) {
            pixel_selected<false>(input, weights, biases, multipliers, shifts, output_y,
                         output_x, output, regions);
            output += Channels;
          }
        } else {
          for (int output_x = 0; output_x < OutputWidth; ++output_x) {
            pixel_selected<false>(input, weights, biases, multipliers, shifts, output_y,
                         output_x, output, regions);
            output += Channels;
          }
        }
      }
      input += InputHeight * InputWidth * Channels;
    }
  }
};

template <int Batches, int InputHeight, int InputWidth, int Channels,
          int OutputHeight, int OutputWidth, int FilterSize, int StrideHeight,
          int StrideWidth, int PaddingTop, int PaddingLeft, int InputOffset,
          int OutputOffset, int ActivationMin, int ActivationMax,
          class Requantization = DefaultRequantization, bool OutlinePixel = false, bool PostIncrement = false, bool CorrectedBiases = false>
inline void depthwise_corrected(const int8_t *input, const int8_t *weights,
                            const int32_t *biases, const int32_t *multipliers,
                            const int32_t *shifts, int8_t *output, const int32_t *regions = nullptr) {
  DepthwiseCorrected<Batches, InputHeight, InputWidth, Channels, OutputHeight,
                 OutputWidth, FilterSize, StrideHeight, StrideWidth, PaddingTop,
                 PaddingLeft, InputOffset, OutputOffset, ActivationMin,
                 ActivationMax, Requantization, OutlinePixel, PostIncrement, CorrectedBiases>::run(input, weights, biases,
                                                     multipliers, shifts, output, regions);
}
} // namespace arch_project
