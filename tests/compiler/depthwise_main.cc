// Exact whole-tensor checks against pinned TFLM, including every border byte.
#include "kernels/rv64imc/depthwise.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/depthwise_conv.h"
#include <array>
#include <cstdio>
#include <vector>

static uint32_t state = 0x39458712;
static uint32_t random_word() {
  state = state * 1664525u + 1013904223u;
  return state;
}
static int8_t random_byte() {
  return static_cast<int8_t>(static_cast<int>(random_word() >> 24) - 128);
}
static unsigned cases = 0, bytes = 0;

template <int B, int H, int W, int C, int OH, int OW, int K, int SH, int SW,
          int PH, int PW, int IO, int OO, int Min, int Max>
bool check() {
  std::vector<int8_t> input(B * H * W * C), weights(K * K * C),
      actual(B * OH * OW * C + 2), expected(B * OH * OW * C);
  std::array<int32_t, C> bias{}, multipliers{}, shifts{};
  const int32_t idims[] = {B, H, W, C}, wdims[] = {1, K, K, C};
  const int32_t odims[] = {B, OH, OW, C}, bdims[] = {C};
  for (int trial = 0; trial < 32; ++trial) {
    for (auto &x : input)
      x = trial == 0   ? -128
          : trial == 1 ? 127
          : trial == 2 ? -IO
                       : random_byte();
    for (auto &w : weights)
      w = trial == 0 ? -128 : trial == 1 ? 127 : random_byte();
    for (int c = 0; c < C; ++c) {
      bias[c] = static_cast<int32_t>(random_word() % 200001) - 100000;
      multipliers[c] = 0x40000000 + (random_word() & 0x3fffffff);
      constexpr int shift_values[] = {-20, -8, -1, 0, 1, 2};
      shifts[c] = shift_values[(trial + c) % 6];
    }
    tflite::DepthwiseParams p{};
    p.input_offset = IO;
    p.output_offset = OO;
    p.stride_height = SH;
    p.stride_width = SW;
    p.dilation_height_factor = p.dilation_width_factor = p.depth_multiplier = 1;
    p.padding_values.height = PH;
    p.padding_values.width = PW;
    p.quantized_activation_min = Min;
    p.quantized_activation_max = Max;
    const int32_t *bias_ptr = trial % 2 ? bias.data() : nullptr;
    const auto original_input = input, original_weights = weights;
    tflite::reference_integer_ops::DepthwiseConvPerChannel(
        p, multipliers.data(), shifts.data(), tflite::RuntimeShape(4, idims),
        input.data(), tflite::RuntimeShape(4, wdims), weights.data(),
        tflite::RuntimeShape(1, bdims), bias_ptr,
        tflite::RuntimeShape(4, odims), expected.data());
    actual.front() = 53;
    actual.back() = -87;
    arch_project::depthwise_fixed<B, H, W, C, OH, OW, K, SH, SW, PH, PW, IO, OO,
                                  Min, Max>(input.data(), weights.data(),
                                            bias_ptr, multipliers.data(),
                                            shifts.data(), actual.data() + 1);
    if (actual.front() != 53 || actual.back() != -87 ||
        input != original_input || weights != original_weights)
      return false;
    for (unsigned i = 0; i < expected.size(); ++i)
      if (actual[i + 1] != expected[i]) {
        std::fprintf(
            stderr, "K=%d H=%d W=%d C=%d trial=%d byte=%u got=%d expected=%d\n",
            K, H, W, C, trial, i, actual[i + 1], expected[i]);
        return false;
      }
    ++cases;
    bytes += expected.size();
  }
  return true;
}
int main() {
  if (!check<1, 56, 56, 144, 56, 56, 3, 1, 1, 1, 1, 128, -128, -128, 127>() ||
      !check<1, 28, 28, 240, 28, 28, 5, 1, 1, 2, 2, 128, -128, -128, 127>() ||
      !check<1, 8, 10, 3, 4, 5, 3, 2, 2, 0, 0, -127, 17, -30, 90>() ||
      !check<1, 8, 10, 7, 4, 5, 5, 2, 2, 1, 1, 7, 0, -128, 127>() ||
      !check<2, 9, 8, 1, 3, 6, 3, 2, 1, 0, 0, 0, -7, -128, 127>() ||
      !check<1, 5, 6, 5, 1, 2, 5, 1, 1, 0, 0, -32, 127, -80, 80>() ||
      !check<1, 1, 1, 3, 1, 1, 3, 1, 1, 1, 1, 128, -128, -128, 127>() ||
      !check<1, 2, 3, 7, 2, 3, 5, 1, 1, 2, 2, -127, 0, -128, 127>() ||
      !check<1, 4, 7, 2, 4, 4, 5, 1, 2, 2, 2, 17, 9, -10, 127>() ||
      !check<1, 3, 3, 1, 3, 3, 3, 1, 1, 1, 1, 0, 0, 0, 127>())
    return 1;
  std::printf("depthwise: %u kernel cases, %u complete output bytes: PASS\n",
              cases, bytes);
}
