// NHWC x 1HWO scalar depthwise convolution; depth multiplier and dilation 1.
// Quantization and row-major accumulation order match the pinned reference.
#pragma once

#include "quantization_select.h"
#include <cstdint>

namespace arch_project {

// Static geometry keeps address strides constant. Interior taps are unrolled;
// border bounds are clipped once per pixel, outside the channel loop. Invalid
// taps contribute nothing (including input offset), as in the reference.
template <int Batches, int Height, int Width, int Channels, int OutputHeight,
          int OutputWidth, int Filter, int StrideH, int StrideW, int PadH,
          int PadW, int InputOffset, int OutputOffset, int Min, int Max>
struct DepthwiseFixed {
  static_assert(Filter == 3 || Filter == 5);
  static_assert(Batches > 0 && Height > 0 && Width > 0 && Channels > 0 &&
                OutputHeight > 0 && OutputWidth > 0);
  static_assert((StrideH == 1 || StrideH == 2) &&
                (StrideW == 1 || StrideW == 2));
  static_assert(PadH >= 0 && PadW >= 0);
  static_assert(Min >= -128 && Max <= 127 && Min <= Max);
  static constexpr int clamp(int x, int limit) {
    return x < 0 ? 0 : x > limit ? limit : x;
  }
  static constexpr int first_y =
      clamp((PadH + StrideH - 1) / StrideH, OutputHeight);
  static constexpr int first_x =
      clamp((PadW + StrideW - 1) / StrideW, OutputWidth);
  // No interior when the input is smaller than the filter. Avoid truncation
  // toward zero for the negative numerator in that case.
  static constexpr int end_y =
      Height < Filter
          ? first_y
          : clamp((Height + PadH - Filter) / StrideH + 1, OutputHeight);
  static constexpr int end_x =
      Width < Filter
          ? first_x
          : clamp((Width + PadW - Filter) / StrideW + 1, OutputWidth);

  template <bool Interior>
  static inline void pixel(const int8_t *input, const int8_t *weights,
                           const int32_t *biases, const int32_t *multipliers,
                           const int32_t *shifts, int y, int x,
                           int8_t *output) {
    const int origin_y = y * StrideH - PadH;
    const int origin_x = x * StrideW - PadW;
    const int fy_begin = origin_y < 0 ? -origin_y : 0;
    const int fx_begin = origin_x < 0 ? -origin_x : 0;
    const int fy_end = origin_y + Filter > Height ? Height - origin_y : Filter;
    const int fx_end = origin_x + Filter > Width ? Width - origin_x : Filter;
    for (int c = 0; c < Channels; ++c) {
      int32_t acc = 0;
      if constexpr (Interior) {
        const int8_t *base =
            input + (origin_y * Width + origin_x) * Channels + c;
        const int8_t *w = weights + c;
#pragma GCC unroll 5
        for (int fy = 0; fy < Filter; ++fy) {
#pragma GCC unroll 5
          for (int fx = 0; fx < Filter; ++fx)
            acc += (static_cast<int32_t>(base[(fy * Width + fx) * Channels]) +
                    InputOffset) *
                   w[(fy * Filter + fx) * Channels];
        }
      } else {
        // Construct pointers only for valid rows/taps; never form a pointer
        // before the input object, even when the origin is negative.
        for (int fy = fy_begin; fy < fy_end; ++fy) {
          for (int fx = fx_begin; fx < fx_end; ++fx)
            acc += (static_cast<int32_t>(
                        input[((origin_y + fy) * Width + origin_x + fx) *
                                  Channels +
                              c]) +
                    InputOffset) *
                   weights[(fy * Filter + fx) * Channels + c];
        }
      }
      if (biases)
        acc += biases[c];
      acc =
          ARCH_PROJECT_MULTIPLIER(acc, multipliers[c], shifts[c]);
      acc += OutputOffset;
      if (acc < Min)
        acc = Min;
      if (acc > Max)
        acc = Max;
      output[c] = static_cast<int8_t>(acc);
    }
  }

  static inline void run(const int8_t *input, const int8_t *weights,
                         const int32_t *biases, const int32_t *multipliers,
                         const int32_t *shifts, int8_t *output) {
    for (int batch = 0; batch < Batches; ++batch) {
      for (int y = 0; y < OutputHeight; ++y) {
        if (y >= first_y && y < end_y) {
          for (int x = 0; x < first_x; ++x) {
            pixel<false>(input, weights, biases, multipliers, shifts, y, x,
                         output);
            output += Channels;
          }
          for (int x = first_x; x < end_x; ++x) {
            pixel<true>(input, weights, biases, multipliers, shifts, y, x,
                        output);
            output += Channels;
          }
          for (int x = end_x; x < OutputWidth; ++x) {
            pixel<false>(input, weights, biases, multipliers, shifts, y, x,
                         output);
            output += Channels;
          }
        } else {
          for (int x = 0; x < OutputWidth; ++x) {
            pixel<false>(input, weights, biases, multipliers, shifts, y, x,
                         output);
            output += Channels;
          }
        }
      }
      input += Height * Width * Channels;
    }
  }
};

template <int Batches, int Height, int Width, int Channels, int OutputHeight,
          int OutputWidth, int Filter, int StrideH, int StrideW, int PadH,
          int PadW, int InputOffset, int OutputOffset, int Min, int Max>
inline void depthwise_fixed(const int8_t *input, const int8_t *weights,
                            const int32_t *biases, const int32_t *multipliers,
                            const int32_t *shifts, int8_t *output) {
  DepthwiseFixed<Batches, Height, Width, Channels, OutputHeight, OutputWidth,
                 Filter, StrideH, StrideW, PadH, PadW, InputOffset,
                 OutputOffset, Min, Max>::run(input, weights, biases,
                                              multipliers, shifts, output);
}
} // namespace arch_project
