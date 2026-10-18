// Adapted scalar fixed-point algorithms: see NOTICE and LICENSE.
#include "softmax.h"
#include "quantization.h"
#include <algorithm>
namespace arch_project::numeric {
int32_t exp_negative_q5(int32_t scaled_difference_q5) {
  // Q5.26: five magnitude bits, 26 fractional bits, plus the sign bit.
  // Reduce to [-1/4,0), then evaluate the pinned polynomial around -1/8.
  // Multiplying the reduced raw value by 32 converts it to Q0.31.
  const int32_t quarter = 1 << 24;
  const int32_t reduced_difference_q5 =
      (scaled_difference_q5 & (quarter - 1)) - quarter;
  const int32_t polynomial_input_q0 = reduced_difference_q5 * 32 + (1 << 28);
  const int32_t squared_q0 = high_mul(polynomial_input_q0, polynomial_input_q0),
                cubed_q0 = high_mul(squared_q0, polynomial_input_q0),
                fourth_power_q0 = high_mul(squared_q0, squared_q0);
  // Taylor terms through fourth order, grouped to preserve reference rounding.
  // 715827883 represents 1/3 in Q0.31; 1895147668 represents exp(-1/8).
  const int32_t higher_terms_q0 = divide_pot(
      high_mul(divide_pot(fourth_power_q0, 2) + cubed_q0, 715827883) +
          squared_q0,
      1);
  int32_t exponential_q0 =
      1895147668 + high_mul(1895147668, polynomial_input_q0 + higher_terms_q0);
  const int32_t remaining_difference_q5 =
      reduced_difference_q5 - scaled_difference_q5;
  // exp(-1/4), exp(-1/2), exp(-1), ..., exp(-16), all in Q0.31.
  // Each set bit in the remaining difference selects one factor.
  constexpr int32_t exponential_factors_q0[] = {
      1672461947, 1302514674, 790015084, 290630308, 39332535, 720401, 242};
#pragma GCC unroll 7
  for (int i = 0; i < 7; ++i)
    if (remaining_difference_q5 & (1 << (24 + i)))
      exponential_q0 = high_mul(exponential_q0, exponential_factors_q0[i]);
  return scaled_difference_q5 == 0 ? INT32_MAX : exponential_q0;
}
int32_t reciprocal(int32_t value, int integer_bits, int *exponent_bits) {
  // Normalize the positive sum to [1,2); retain its binary exponent separately.
  const int headroom = __builtin_clz(static_cast<uint32_t>(value));
  *exponent_bits = integer_bits - headroom;
  const int32_t normalized_fraction_q0 = static_cast<int32_t>(
      (static_cast<uint32_t>(value) << headroom) - (uint32_t{1} << 31));
  const int32_t half_denominator_q0 = static_cast<int32_t>(
      (static_cast<int64_t>(normalized_fraction_q0) + INT32_MAX + 1) / 2);
  // Newton-Raphson reciprocal estimate in Q2.29. The seed coefficients are
  // 48/17 and -32/17. Keep the same three iterations and rounding points.
  int32_t estimate_q2 = 1515870810 + high_mul(half_denominator_q0, -1010580540);
  for (int i = 0; i < 3; ++i) {
    const int32_t error_q2 =
        (1 << 29) - high_mul(half_denominator_q0, estimate_q2);
    // estimate*error is Q4.27; shift by two to restore its Q2.29 correction.
    estimate_q2 += saturating_left(high_mul(estimate_q2, error_q2), 2);
  }
  return saturating_left(estimate_q2, 1);
}
int softmax(const int8_t *input, int depth, int32_t multiplier, int left_shift,
            int diff_min, int8_t *output, int32_t *sum_raw, int *exponent) {
  if (!input || !output || !sum_raw || !exponent || depth <= 0 ||
      depth > 1000 || multiplier <= 0 || left_shift < 0 || left_shift > 30 ||
      diff_min > 0)
    return 1;
  // Pass 1 finds the stable reference origin: every difference is <= 0.
  const int maximum_input = *std::max_element(input, input + depth);
  // Pass 2 accumulates rounded exponentials in Q12.19. Use a wide sum to
  // diagnose overflow before normalization, without changing reference values.
  int64_t sum_of_exponentials_q12 = 0;
  for (int channel = 0; channel < depth; ++channel) {
    const int input_difference = input[channel] - maximum_input;
    if (input_difference >= diff_min) {
      const int64_t shifted_difference =
          static_cast<int64_t>(input_difference) * (int64_t{1} << left_shift);
      if (shifted_difference < INT32_MIN || shifted_difference > INT32_MAX)
        return 1;
      sum_of_exponentials_q12 += divide_pot(
          exp_negative_q5(greater(input_difference, multiplier, left_shift)),
          12);
    }
  }
  if (sum_of_exponentials_q12 <= 0 || sum_of_exponentials_q12 > INT32_MAX)
    return 1;
  *sum_raw = static_cast<int32_t>(sum_of_exponentials_q12);
  int normalization_bits;
  const int32_t normalization_scale_q0 =
      reciprocal(*sum_raw, 12, &normalization_bits);
  *exponent = normalization_bits + 31 - 8;
  if (*exponent < 0 || *exponent > 31)
    return 2;
  // The checked sum is the same Q12 sum the reference recomputes after its
  // preflight. Reuse it; preserve the exponent failure before any output write.
  // Pass 3 rescales probabilities to INT8. -128 encodes probability zero;
  // values below diff_min are deliberately skipped by the reference algorithm.
  for (int channel = 0; channel < depth; ++channel) {
    const int input_difference = input[channel] - maximum_input;
    if (input_difference < diff_min) {
      output[channel] = -128;
    } else {
      const int32_t scaled_difference_q5 =
          greater(input_difference, multiplier, left_shift);
      const int32_t exponential_q0 = exp_negative_q5(scaled_difference_q5);
      const int32_t scaled_exponential_q0 =
          high_mul(normalization_scale_q0, exponential_q0);
      const int32_t output_level = divide_pot(scaled_exponential_q0, *exponent);
      output[channel] =
          static_cast<int8_t>(clamp(output_level - 128, -128, 127));
    }
  }
  return 0;
}
} // namespace arch_project::numeric
