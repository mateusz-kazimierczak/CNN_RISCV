// Compare every output byte with the pinned kernel over directed/random data.
#include "kernels/rv64imc/pointwise.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/conv.h"
#include <array>
#include <cstdio>
#include <vector>

static uint32_t state = 0x12345678;
static uint32_t random_word() {
  state = state * 1664525u + 1013904223u;
  return state;
}
static int8_t random_byte() {
  return static_cast<int8_t>(static_cast<int>(random_word() >> 24) - 128);
}

template <int K, int C, int Offset, int Min, int Max> bool check() {
  constexpr int Pixels = 3;
  std::vector<int8_t> input(Pixels * K), weights(C * K), actual(Pixels * C + 2),
      expected(Pixels * C);
  std::array<int32_t, C> biases{}, corrected{}, multipliers{}, shifts{};
  const int32_t idims[] = {1, 1, Pixels, K}, wdims[] = {C, 1, 1, K};
  const int32_t bdims[] = {C}, odims[] = {1, 1, Pixels, C};
  for (int trial = 0; trial < 40; ++trial) {
    const int zero = trial % 3 == 0   ? -128
                     : trial % 3 == 1 ? 127
                                      : random_byte();
    for (auto &x : input)
      x = trial == 0   ? -128
          : trial == 1 ? 127
          : trial == 2 ? zero
                       : random_byte();
    for (auto &w : weights)
      w = trial == 0 ? -128 : trial == 1 ? 127 : random_byte();
    for (int c = 0; c < C; ++c) {
      biases[c] = static_cast<int32_t>(random_word() % 200001) - 100000;
      int32_t sum = 0;
      for (int k = 0; k < K; ++k)
        sum += weights[c * K + k];
      corrected[c] = biases[c] - zero * sum;
      multipliers[c] = 0x40000000 + (random_word() & 0x3fffffff);
      constexpr int shift_values[] = {-20, -8, -1, 0, 1, 2};
      shifts[c] = shift_values[(trial + c) % 6];
    }
    tflite::ConvParams p{};
    p.input_offset = -zero;
    p.output_offset = Offset;
    p.stride_height = p.stride_width = p.dilation_height_factor =
        p.dilation_width_factor = 1;
    p.quantized_activation_min = Min;
    p.quantized_activation_max = Max;
    tflite::reference_integer_ops::ConvPerChannel(
        p, multipliers.data(), shifts.data(), tflite::RuntimeShape(4, idims),
        input.data(), tflite::RuntimeShape(4, wdims), weights.data(),
        tflite::RuntimeShape(1, bdims), biases.data(),
        tflite::RuntimeShape(4, odims), expected.data());
    auto reset = [&]() {
      std::fill(actual.begin(), actual.end(), int8_t{-91});
      actual.front() = 57;
      actual.back() = -83;
    };
    auto matches = [&](int block) {
      if (actual.front() != 57 || actual.back() != -83)
        return false;
      for (int i = 0; i < Pixels * C; ++i)
        if (actual[i + 1] != expected[i]) {
          std::fprintf(
              stderr,
              "K=%d C=%d block=%d trial=%d byte=%d got=%d expected=%d\n", K, C,
              block, trial, i, actual[i + 1], expected[i]);
          return false;
        }
      return true;
    };
    reset();
    arch_project::pointwise_dot8<Pixels, K, C, Offset, Min, Max>(
        input.data(), weights.data(), corrected.data(), multipliers.data(),
        shifts.data(), actual.data() + 1);
    if (!matches(1))
      return false;
    if constexpr (C % 2 == 0) {
      reset();
      arch_project::pointwise_dot8_blocked<Pixels, K, C, Offset, Min, Max, 2>(
          input.data(), weights.data(), corrected.data(), multipliers.data(),
          shifts.data(), actual.data() + 1);
      if (!matches(2))
        return false;
    }
    if constexpr (C % 4 == 0) {
      reset();
      arch_project::pointwise_dot8_blocked<Pixels, K, C, Offset, Min, Max, 4>(
          input.data(), weights.data(), corrected.data(), multipliers.data(),
          shifts.data(), actual.data() + 1);
      if (!matches(4))
        return false;
    }
  }
  return true;
}

int main() {
  if (!check<8, 3, -128, -128, 127>() || !check<8, 6, 0, -128, 127>() ||
      !check<24, 12, -7, -80, 100>() || !check<16, 96, 17, -20, 90>() ||
      !check<320, 1280, 127, -128, 127>())
    return 1;
  std::puts("pointwise: 200 fixtures, 480 kernel cases, 501480 complete output "
            "bytes: PASS");
}
