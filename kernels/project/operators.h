// Static operator subsets; reference-compatible integer arithmetic. See NOTICE.
#pragma once
#include "quantization.h"
#include <cstdint>
#include <limits>
namespace arch_project {
// RGB, 3x3, stride-two convolution, NHWC x OHWI. Bias follows reduction.
template <int H, int W, int OC, int OH, int OW, int PH, int PW, int IO, int OO,
          int Min, int Max>
__attribute__((always_inline)) inline void
stem_rgb(const int8_t *input, const int8_t *weights, const int32_t *bias,
         const int32_t *multipliers, const int32_t *shifts, int8_t *output) {
  for (int y = 0; y < OH; ++y)
    for (int x = 0; x < OW; ++x) {
      const int oy = y * 2 - PH, ox = x * 2 - PW;
      for (int c = 0; c < OC; ++c) {
        int32_t acc = 0;
        for (int fy = 0; fy < 3; ++fy) {
          const int iy = oy + fy;
          if (iy < 0 || iy >= H)
            continue;
          for (int fx = 0; fx < 3; ++fx) {
            const int ix = ox + fx;
            if (ix < 0 || ix >= W)
              continue;
            const int8_t *in = input + (iy * W + ix) * 3;
            const int8_t *w = weights + c * 27 + (fy * 3 + fx) * 3;
#pragma GCC unroll 3
            for (int k = 0; k < 3; ++k)
              acc += (static_cast<int32_t>(in[k]) + IO) * w[k];
          }
        }
        if (bias)
          acc += bias[c];
        *output++ = static_cast<int8_t>(numeric::clamp(
            numeric::multiply(acc, multipliers[c], shifts[c]) + OO, Min, Max));
      }
    }
}

template <int Batches, int K, int OC, int IO, int OO, int M, int S, int Min,
          int Max>
inline void fully_connected(const int8_t *input, const int8_t *weights,
                            const int32_t *bias, int8_t *output) {
  for (int b = 0; b < Batches; ++b) {
    for (int c = 0; c < OC; ++c) {
      int32_t acc = 0;
      const int8_t *w = weights + c * K;
      int k = 0;
      // Same eight-product grouping as the convolution reduction, with the
      // input offset retained here. No new corrected-bias payload is needed.
      for (; k + 8 <= K; k += 8) {
#pragma GCC unroll 8
        for (int lane = 0; lane < 8; ++lane)
          acc += (static_cast<int32_t>(input[k + lane]) + IO) * w[k + lane];
      }
      for (; k < K; ++k)
        acc += (static_cast<int32_t>(input[k]) + IO) * w[k];
      if (bias)
        acc += bias[c];
      *output++ = static_cast<int8_t>(
          numeric::clamp(numeric::multiply(acc, M, S) + OO, Min, Max));
    }
    input += K;
  }
}

template <int N, int AO, int BO, int OO, int AM, int BM, int OM, int AS, int BS,
          int OS, int Left, int Min, int Max>
inline void add(const int8_t *a, const int8_t *b, int8_t *output) {
  static_assert(AS <= 0 && BS <= 0 && OS <= 0);
  for (int i = 0; i < N; ++i) {
    const int32_t x = numeric::smaller((a[i] + AO) * (1 << Left), AM, AS);
    const int32_t y = numeric::smaller((b[i] + BO) * (1 << Left), BM, BS);
    output[i] = static_cast<int8_t>(
        numeric::clamp(numeric::smaller(x + y, OM, OS) + OO, Min, Max));
  }
}

template <int Batches, int Pixels, int Channels, int Min, int Max>
inline void global_average(const int8_t *input, int8_t *output) {
  static_assert(Pixels > 0 && Pixels <= INT32_MAX / 129);
  for (int b = 0; b < Batches; ++b) {
    for (int c = 0; c < Channels; ++c) {
      int32_t sum = 0;
      for (int p = 0; p < Pixels; ++p)
        sum += input[p * Channels + c];
      // C++ division truncates toward zero; reference rounding is away from
      // zero at a half, with count/2 truncated before adding/subtracting.
      const int32_t average =
          (sum > 0 ? sum + Pixels / 2 : sum - Pixels / 2) / Pixels;
      *output++ = static_cast<int8_t>(numeric::clamp(average, Min, Max));
    }
    input += Pixels * Channels;
  }
}

template <class Input, class Output, int N, int M, int S, int IZ, int OZ>
inline void boundary(const Input *input, Output *output) {
  if constexpr (M == (1 << 30) && S == 1 &&
                ((std::numeric_limits<Input>::min() == -128 &&
                  IZ - OZ == -128) ||
                 (std::numeric_limits<Input>::min() == 0 && IZ - OZ == 128))) {
    for (int i = 0; i < N; ++i)
      output[i] = static_cast<Output>(input[i] ^ 0x80);
  } else {
    for (int i = 0; i < N; ++i)
      output[i] = static_cast<Output>(numeric::clamp(
          numeric::multiply(static_cast<int32_t>(input[i]) - IZ, M, S) + OZ,
          std::numeric_limits<Output>::min(),
          std::numeric_limits<Output>::max()));
  }
}
} // namespace arch_project
