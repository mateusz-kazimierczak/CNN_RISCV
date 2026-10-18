#include "kernels/project/quantization.h"
#include "kernels/project/softmax.h"
#include "numerics.h"
#include "tensorflow/lite/kernels/internal/common.h"
#include <array>
#include <cstdio>
#include <vector>
using namespace arch_project::numeric;
static uint32_t state = 0x42514591;
static uint32_t random_word() {
  state = state * 1664525u + 1013904223u;
  return state;
}
int main() {
  constexpr int32_t edges[] = {
      INT32_MIN, INT32_MIN + 1, -1073741824, -3, -2, -1, 0, 1, 2,
      3,         1073741824,    INT32_MAX};
  for (int32_t a : edges)
    for (int32_t b : edges)
      if (high_mul(a, b) != gemmlowp::SaturatingRoundingDoublingHighMul(a, b))
        return 1;
  // Specialized policy domain: every shift, extreme/nonnegative multipliers,
  // and signed endpoints. In particular, 0.5 multipliers exercise positive
  // and negative high-multiply ties (whose rounding differs from divide_pot).
  constexpr int32_t multipliers[] = {0, 1, 2, 3, (1 << 30) - 1,
                                     1 << 30, (1 << 30) + 1, INT32_MAX};
  auto check_nonpositive = [](int32_t x, int32_t m, int shift) {
    const int32_t expected = tflite::MultiplyByQuantizedMultiplier(x, m, shift);
    return multiply_nonpositive(x, m, shift) == expected &&
           multiply_nonpositive_inline(x, m, shift) == expected;
  };
  for (int32_t x : edges)
    for (int32_t m : multipliers)
      for (int shift = -31; shift <= 0; ++shift)
        if (!check_nonpositive(x, m, shift))
          return 9;
  // Every power-of-two transition plus its neighbours, including the second
  // rounding stage's halfway values. Avoid forming out-of-range INT32 values.
  for (int bit = 0; bit <= 31; ++bit)
    for (int sign : {-1, 1})
      for (int delta = -2; delta <= 2; ++delta) {
        const int64_t wide = sign * (int64_t{1} << bit) + delta;
        if (wide < INT32_MIN || wide > INT32_MAX)
          continue;
        for (int32_t m : multipliers)
          for (int shift = -31; shift <= 0; ++shift)
            if (!check_nonpositive(static_cast<int32_t>(wide), m, shift))
              return 10;
      }
  for (int i = 0; i < 200000; ++i) {
    const int32_t x = static_cast<int32_t>(random_word());
    const int32_t m = static_cast<int32_t>(random_word() & INT32_MAX);
    for (int specialized_shift = -31; specialized_shift <= 0; ++specialized_shift)
      if (!check_nonpositive(x, m, specialized_shift))
        return 11;
    const int shift = static_cast<int>(random_word() % 62) - 31;
    const int left = shift > 0 ? shift : 0;
    const int32_t safe = x / (int64_t{1} << left);
    if (multiply(safe, m, shift) !=
        tflite::MultiplyByQuantizedMultiplier(safe, m, shift))
      return 2;
    for (int e = 0; e < 32; ++e)
      if (divide_pot(x, e) != gemmlowp::RoundingDivideByPOT(x, e))
        return 3;
    const int32_t neg = x > 0 ? -x : x;
    const int32_t expected_exp =
        gemmlowp::exp_on_negative_values(
            gemmlowp::FixedPoint<int32_t, 5>::FromRaw(neg))
            .raw();
    if (exp_negative_q5(neg) != expected_exp) {
      std::printf("exp %d: %d != %d\n", neg, exp_negative_q5(neg),
                  expected_exp);
      return 4;
    }
    const int32_t positive = (x & INT32_MAX) | 1;
    int a, b;
    if (reciprocal(positive, 12, &a) !=
            tflite::GetReciprocal(positive, 12, &b) ||
        a != b)
      return 5;
  }
  // Directed zero, near-zero and barrel-shifter transitions in Q5.26.
  for (int bit = 0; bit < 31; ++bit)
    for (int delta = -2; delta <= 2; ++delta) {
      const int64_t wide = -(int64_t{1} << bit) + delta;
      if (wide > 0 || wide < INT32_MIN)
        continue;
      const int32_t x = static_cast<int32_t>(wide);
      if (exp_negative_q5(x) !=
          gemmlowp::exp_on_negative_values(
              gemmlowp::FixedPoint<int32_t, 5>::FromRaw(x))
              .raw())
        return 6;
    }
  for (int depth : {1, 2, 7, 49, 1000})
    for (int trial = 0; trial < 40; ++trial) {
      std::vector<int8_t> input(depth), actual(depth + 2, 61),
          expected(depth, -77);
      for (auto &x : input)
        x = trial == 0   ? -128
            : trial == 1 ? 127
            : trial == 2 ? 0
                         : static_cast<int8_t>(random_word() >> 24);
      int32_t sa = 0, sb = 0;
      int ea = 0, eb = 0;
      const int32_t m = trial % 2 ? 1717986944 : 1073741824;
      const int left = 20 + (trial % 4);
      const int diff_min = -255 + (trial % 40);
      const auto old = expected;
      const int a = softmax(input.data(), depth, m, left, diff_min,
                            actual.data() + 1, &sa, &ea);
      const int b = cc_softmax(input.data(), depth, m, left, diff_min,
                               expected.data(), &sb, &eb);
      if (a != b || sa != sb || ea != eb || actual.front() != 61 ||
          actual.back() != 61)
        return 7;
      for (int i = 0; i < depth; ++i)
        if (a == 0 ? actual[i + 1] != expected[i]
                   : actual[i + 1] != 61 || expected != old)
          return 8;
    }
  std::puts("project numerics: both nonpositive policies match 6400000 random "
            "scales plus directed edges/ties; 200000 random scales/exp/reciprocals, 6400000 "
            "rounding cases, 200 complete Softmax cases: PASS");
}
