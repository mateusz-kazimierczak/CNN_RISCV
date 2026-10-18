// Independent full-output oracle checks, including a one-pixel-only tail.
#include "kernels/project/quantization.h"
#include "kernels/rv64imc/pointwise.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/conv.h"
#include <array>
#include <cstdio>
#include <vector>

static uint32_t state = 0x1f687b94;
static uint32_t random_word() {
  state = state * 1664525u + 1013904223u;
  return state;
}
static int8_t random_byte() { return static_cast<int8_t>(random_word() >> 24); }
static int fixtures = 0, calls = 0;
static uint64_t compared_bytes = 0;

template <int Pixels, int K, int C, int Offset, int Min, int Max, int Batches = 1>
bool check() {
  static_assert(Pixels % Batches == 0);
  std::vector<int8_t> input(Pixels * K), weights(C * K), actual(Pixels * C + 2),
      expected(Pixels * C);
  std::array<int32_t, C> bias{}, corrected{}, multipliers{}, shifts{};
  const int32_t idims[] = {Batches, 1, Pixels / Batches, K};
  const int32_t odims[] = {Batches, 1, Pixels / Batches, C};
  const int32_t wdims[] = {C, 1, 1, K}, bdims[] = {C};
  for (int trial = 0; trial < 40; ++trial) {
    const int zero = trial % 3 == 0 ? -128 : trial % 3 == 1 ? 127 : random_byte();
    for (auto &x : input)
      x = trial == 0 ? -128 : trial == 1 ? 127 : trial == 2 ? zero : random_byte();
    for (auto &w : weights)
      w = trial == 0 ? -128 : trial == 1 ? 127 : random_byte();
    const bool positive_shift = trial % 7 == 6;
    for (int c = 0; c < C; ++c) {
      bias[c] = static_cast<int32_t>(random_word() % 200001) - 100000;
      int32_t sum = 0;
      for (int k = 0; k < K; ++k) sum += weights[c * K + k];
      corrected[c] = bias[c] - zero * sum;
      multipliers[c] = 0x40000000 + (random_word() & 0x3fffffff);
      constexpr int values[] = {-31, -20, -8, -1, 0};
      shifts[c] = positive_shift ? 2 : values[(trial + c) % 5];
    }
    tflite::ConvParams p{};
    p.input_offset = -zero;
    p.output_offset = Offset;
    p.stride_height = p.stride_width = p.dilation_height_factor = p.dilation_width_factor = 1;
    p.quantized_activation_min = Min;
    p.quantized_activation_max = Max;
    tflite::reference_integer_ops::ConvPerChannel(
        p, multipliers.data(), shifts.data(), tflite::RuntimeShape(4, idims), input.data(),
        tflite::RuntimeShape(4, wdims), weights.data(), tflite::RuntimeShape(1, bdims), bias.data(),
        tflite::RuntimeShape(4, odims), expected.data());
    ++fixtures;
    auto matches = [&]() {
      ++calls;
      if (actual.front() != 57 || actual.back() != -83) return false;
      for (int i = 0; i < Pixels * C; ++i) {
        ++compared_bytes;
        if (actual[i + 1] != expected[i]) {
          std::fprintf(stderr, "pixels=%d K=%d C=%d trial=%d byte=%d\n", Pixels, K, C, trial, i);
          return false;
        }
      }
      return true;
    };
    auto reset = [&]() {
      std::fill(actual.begin(), actual.end(), int8_t{-91});
      actual.front() = 57;
      actual.back() = -83;
    };
#define CHECK_SPATIAL(BLOCK, POLICY) \
    reset(); \
    arch_project::pointwise_dot8_spatial2<Pixels, K, C, Offset, Min, Max, BLOCK, \
      arch_project::ScalarDot8SpatialBlock, POLICY>(input.data(), weights.data(), \
      corrected.data(), multipliers.data(), shifts.data(), actual.data() + 1); \
    if (!matches()) return false
    CHECK_SPATIAL(2, arch_project::DefaultRequantization);
    CHECK_SPATIAL(2, arch_project::numeric::GenericRequantization);
    if (!positive_shift) {
      CHECK_SPATIAL(2, arch_project::numeric::NonpositiveRequantization);
      CHECK_SPATIAL(2, arch_project::numeric::InlineNonpositiveRequantization);
    }
    if constexpr (C % 4 == 0) {
      CHECK_SPATIAL(4, arch_project::DefaultRequantization);
      CHECK_SPATIAL(4, arch_project::numeric::GenericRequantization);
      if (!positive_shift) {
        CHECK_SPATIAL(4, arch_project::numeric::NonpositiveRequantization);
        CHECK_SPATIAL(4, arch_project::numeric::InlineNonpositiveRequantization);
      }
    }
#undef CHECK_SPATIAL
  }
  return true;
}

int main() {
  if (!check<1, 8, 2, -128, -128, 127>() || !check<2, 8, 4, 127, -128, 127>() ||
      !check<3, 16, 8, -7, -80, 100>() || !check<4, 24, 12, 17, -20, 90>() ||
      !check<49, 320, 32, 127, -128, 127>() || !check<6, 16, 6, 0, -128, 127, 2>())
    return 1;
  std::printf("spatial pointwise: %d fixtures, %d calls, %llu output bytes; all policies, tails and batches: PASS\n",
              fixtures, calls, static_cast<unsigned long long>(compared_bytes));
}
