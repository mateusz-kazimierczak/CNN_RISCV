#include "kernels/project/operators.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/add.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/conv.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/fully_connected.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/pooling.h"
#include "tensorflow/lite/kernels/internal/reference/requantize.h"
#include <array>
#include <cstdio>
#include <vector>
static uint32_t rng = 42;
static int8_t byte() {
  rng = rng * 1664525u + 1013904223u;
  return static_cast<int8_t>(rng >> 24);
}
static bool equal(const std::vector<int8_t> &a, const std::vector<int8_t> &b) {
  return a.front() == 71 && a.back() == -93 &&
         std::equal(b.begin(), b.end(), a.begin() + 1);
}
template <int H, int W, int OC, int PH, int PW, int IO> bool stem() {
  constexpr int OH = (H + 1) / 2, OW = (W + 1) / 2;
  std::vector<int8_t> input(H * W * 3), weights(OC * 27), got(OH * OW * OC + 2),
      want(OH * OW * OC);
  std::array<int32_t, OC> bias{}, m{}, s{};
  int id[] = {1, H, W, 3}, wd[] = {OC, 3, 3, 3}, od[] = {1, OH, OW, OC},
      bd[] = {OC};
  for (int trial = 0; trial < 16; ++trial) {
    for (auto &x : input)
      x = trial == 0 ? -128 : trial == 1 ? 127 : byte();
    for (auto &w : weights)
      w = byte();
    for (int c = 0; c < OC; ++c) {
      bias[c] = byte() * 109;
      m[c] = 1073741824;
      s[c] = -3;
    }
    const int32_t *b = trial % 2 ? bias.data() : nullptr;
    tflite::ConvParams p{};
    p.stride_height = p.stride_width = 2;
    p.dilation_height_factor = p.dilation_width_factor = 1;
    p.padding_values.height = PH;
    p.padding_values.width = PW;
    p.input_offset = IO;
    p.output_offset = -7;
    p.quantized_activation_min = -90;
    p.quantized_activation_max = 100;
    tflite::reference_integer_ops::ConvPerChannel(
        p, m.data(), s.data(), tflite::RuntimeShape(4, id), input.data(),
        tflite::RuntimeShape(4, wd), weights.data(),
        tflite::RuntimeShape(1, bd), b, tflite::RuntimeShape(4, od),
        want.data());
    got.front() = 71;
    got.back() = -93;
    arch_project::stem_rgb<H, W, OC, OH, OW, PH, PW, IO, -7, -90, 100>(
        input.data(), weights.data(), b, m.data(), s.data(), got.data() + 1);
    if (!equal(got, want))
      return false;
  }
  return true;
}
template <int K, int OC, int IO, int Shift> bool fc() {
  constexpr int B = 2;
  std::vector<int8_t> input(B * K), weights(K * OC), got(B * OC + 2),
      want(B * OC);
  std::array<int32_t, OC> bias{};
  int id[] = {B, K}, wd[] = {OC, K}, od[] = {B, OC}, bd[] = {OC};
  for (int trial = 0; trial < 16; ++trial) {
    for (auto &x : input)
      x = trial == 0 ? -128 : trial == 1 ? 127 : byte();
    for (auto &w : weights)
      w = byte();
    for (auto &b : bias)
      b = byte() * 1009;
    auto b = trial % 2 ? bias.data() : nullptr;
    tflite::FullyConnectedParams p{};
    p.input_offset = IO;
    p.output_offset = 17;
    p.output_multiplier = 1717986944;
    p.output_shift = Shift;
    p.quantized_activation_min = -110;
    p.quantized_activation_max = 88;
    tflite::reference_integer_ops::FullyConnected(
        p, tflite::RuntimeShape(2, id), input.data(),
        tflite::RuntimeShape(2, wd), weights.data(),
        tflite::RuntimeShape(1, bd), b, tflite::RuntimeShape(2, od),
        want.data());
    got.front() = 71;
    got.back() = -93;
    arch_project::fully_connected<B, K, OC, IO, 17, 1717986944, Shift, -110,
                                  88>(input.data(), weights.data(), b,
                                      got.data() + 1);
    if (!equal(got, want))
      return false;
  }
  return true;
}
template <int P, int C> bool pool() {
  std::vector<int8_t> input(2 * P * C), got(2 * C + 2), want(2 * C);
  int id[] = {2, 1, P, C}, od[] = {2, 1, 1, C};
  for (int trial = 0; trial < 100; ++trial) {
    for (auto &x : input)
      x = trial == 0 ? -128 : trial == 1 ? 127 : byte();
    tflite::PoolParams p{};
    p.stride_height = p.stride_width = p.filter_height = 1;
    p.filter_width = P;
    p.quantized_activation_min = -80;
    p.quantized_activation_max = 100;
    if (!tflite::reference_integer_ops::AveragePool(
            p, tflite::RuntimeShape(4, id), input.data(),
            tflite::RuntimeShape(4, od), want.data()))
      return false;
    got.front() = 71;
    got.back() = -93;
    arch_project::global_average<2, P, C, -80, 100>(input.data(),
                                                    got.data() + 1);
    if (!equal(got, want))
      return false;
  }
  return true;
}
int main() {
  if (!stem<1, 1, 1, 1, 1, 128>() || !stem<7, 8, 5, 1, 0, 128>() ||
      !stem<8, 7, 3, 0, 1, -127>() || !fc<7, 3, 128, -8>() ||
      !fc<16, 12, -127, 1>() || !fc<1280, 1000, 128, -10>() || !pool<1, 3>() ||
      !pool<3, 7>() || !pool<4, 1>() || !pool<49, 1280>())
    return 1;
  std::vector<int8_t> a(65536), b(65536), got(65538), want(65536);
  for (int x = -128; x <= 127; ++x)
    for (int y = -128; y <= 127; ++y) {
      const int i = (x + 128) * 256 + y + 128;
      a[i] = x;
      b[i] = y;
    }
  tflite::ArithmeticParams p{};
  p.input1_offset = 128;
  p.input2_offset = -17;
  p.output_offset = -3;
  p.left_shift = 20;
  p.input1_multiplier = 1073741824;
  p.input2_multiplier = 1717986944;
  p.output_multiplier = 1234567890;
  p.input1_shift = -2;
  p.input2_shift = -3;
  p.output_shift = -19;
  p.quantized_activation_min = -100;
  p.quantized_activation_max = 90;
  for (int i = 0; i < 65536; ++i)
    want[i] = tflite::reference_integer_ops::AddFunc(a[i], b[i], p);
  got.front() = 71;
  got.back() = -93;
  arch_project::add<65536, 128, -17, -3, 1073741824, 1717986944, 1234567890, -2,
                    -3, -19, 20, -100, 90>(a.data(), b.data(), got.data() + 1);
  if (!equal(got, want))
    return 2;
  std::array<uint8_t, 256> u{}, expected_u{}, actual_u{};
  std::array<int8_t, 256> si{}, expected_s{}, actual_s{};
  for (int i = 0; i < 256; ++i) {
    u[i] = i;
    si[i] = i - 128;
  }
  arch_project::boundary<uint8_t, int8_t, 256, 1073741824, 1, 131, 3>(
      u.data(), actual_s.data());
  tflite::reference_ops::Requantize(u.data(), 256, 1073741824, 1, 131, 3,
                                    expected_s.data());
  if (actual_s != expected_s)
    return 3;
  arch_project::boundary<int8_t, uint8_t, 256, 1073741824, 1, -128, 0>(
      si.data(), actual_u.data());
  tflite::reference_ops::Requantize(si.data(), 256, 1073741824, 1, -128, 0,
                                    expected_u.data());
  if (actual_u != expected_u)
    return 4;
  arch_project::boundary<uint8_t, int8_t, 256, 1717986944, -2, 120, -7>(
      u.data(), actual_s.data());
  tflite::reference_ops::Requantize(u.data(), 256, 1717986944, -2, 120, -7,
                                    expected_s.data());
  if (actual_s != expected_s)
    return 5;
  std::puts("project operators: 96 stem/FC, 400 pool, 65536 ADD pairs, 768 "
            "boundary bytes: PASS");
}
