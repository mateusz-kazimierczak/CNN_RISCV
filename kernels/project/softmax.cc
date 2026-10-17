// Adapted scalar fixed-point algorithms: see NOTICE and LICENSE.
#include "softmax.h"
#include "quantization.h"
#include <algorithm>
namespace arch_project::numeric {
int32_t exp_negative_q5(int32_t a) {
  // Reduce to [-1/4,0), evaluating the pinned polynomial around -1/8.
  const int32_t quarter = 1 << 24;
  const int32_t reduced = (a & (quarter - 1)) - quarter;
  const int32_t x = reduced * 32 + (1 << 28);
  const int32_t x2 = high_mul(x, x), x3 = high_mul(x2, x),
                x4 = high_mul(x2, x2);
  const int32_t correction =
      divide_pot(high_mul(divide_pot(x4, 2) + x3, 715827883) + x2, 1);
  int32_t result = 1895147668 + high_mul(1895147668, x + correction);
  const int32_t remainder = reduced - a;
  constexpr int32_t factors[] = {1672461947, 1302514674, 790015084, 290630308,
                                 39332535,   720401,     242};
#pragma GCC unroll 7
  for (int i = 0; i < 7; ++i)
    if (remainder & (1 << (24 + i)))
      result = high_mul(result, factors[i]);
  return a == 0 ? INT32_MAX : result;
}
int32_t reciprocal(int32_t value, int integer_bits, int *exponent_bits) {
  const int headroom = __builtin_clz(static_cast<uint32_t>(value));
  *exponent_bits = integer_bits - headroom;
  const int32_t a = static_cast<int32_t>(
      (static_cast<uint32_t>(value) << headroom) - (uint32_t{1} << 31));
  const int32_t half =
      static_cast<int32_t>((static_cast<int64_t>(a) + INT32_MAX + 1) / 2);
  int32_t x = 1515870810 + high_mul(half, -1010580540);
  for (int i = 0; i < 3; ++i) {
    const int32_t error = (1 << 29) - high_mul(half, x);
    x += saturating_left(high_mul(x, error), 2);
  }
  return saturating_left(x, 1);
}
int softmax(const int8_t *input, int depth, int32_t multiplier, int left_shift,
            int diff_min, int8_t *output, int32_t *sum_raw, int *exponent) {
  if (!input || !output || !sum_raw || !exponent || depth <= 0 ||
      depth > 1000 || multiplier <= 0 || left_shift < 0 || left_shift > 30 ||
      diff_min > 0)
    return 1;
  const int maximum = *std::max_element(input, input + depth);
  int64_t sum = 0;
  for (int c = 0; c < depth; ++c) {
    const int diff = input[c] - maximum;
    if (diff >= diff_min) {
      const int64_t shifted =
          static_cast<int64_t>(diff) * (int64_t{1} << left_shift);
      if (shifted < INT32_MIN || shifted > INT32_MAX)
        return 1;
      sum += divide_pot(exp_negative_q5(greater(diff, multiplier, left_shift)),
                        12);
    }
  }
  if (sum <= 0 || sum > INT32_MAX)
    return 1;
  *sum_raw = static_cast<int32_t>(sum);
  int bits;
  const int32_t scale = reciprocal(*sum_raw, 12, &bits);
  *exponent = bits + 31 - 8;
  if (*exponent < 0 || *exponent > 31)
    return 2;
  // The checked sum is the same Q12 sum the reference recomputes after its
  // preflight. Reuse it; preserve the exponent failure before any output write.
  for (int c = 0; c < depth; ++c) {
    const int diff = input[c] - maximum;
    output[c] =
        diff < diff_min
            ? -128
            : static_cast<int8_t>(
                  clamp(divide_pot(
                            high_mul(scale, exp_negative_q5(greater(
                                                diff, multiplier, left_shift))),
                            *exponent) -
                            128,
                        -128, 127));
  }
  return 0;
}
} // namespace arch_project::numeric
