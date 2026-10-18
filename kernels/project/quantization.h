// Scalar INT32 double-rounding arithmetic, adapted from pinned TFLM/common.cc
// and gemmlowp/fixedpoint.h. See NOTICE and LICENSE in this directory.
#pragma once
#include <cstdint>
#include <limits>
namespace arch_project::numeric {
static_assert((-3 >> 1) == -2, "Arithmetic signed right shift required");
// Q0.31 product: round (a*b)/2^31 with the pinned high-multiply convention.
// The sign-dependent nudge compensates for C++ division truncating toward zero.
// INT32_MIN * INT32_MIN is the one saturating case (positive 1 is
// unrepresentable).
inline int32_t high_mul(int32_t a, int32_t b) {
  const int64_t product = static_cast<int64_t>(a) * b;
  const int32_t nudge = product >= 0 ? (1 << 30) : (1 - (1 << 30));
  const int32_t result =
      static_cast<int32_t>((product + nudge) / (int64_t{1} << 31));
  return a == INT32_MIN && b == INT32_MIN ? INT32_MAX : result;
}
// Divide by 2^exponent, exponent in [0,31], rounding to nearest with ties
// away from zero. A plain arithmetic shift has different negative rounding.
inline int32_t divide_pot(int32_t x, int exponent) {
  const int32_t mask = static_cast<int32_t>((int64_t{1} << exponent) - 1);
  const int32_t remainder = x & mask;
  const int32_t threshold = (mask >> 1) + (x < 0 ? 1 : 0);
  return (x >> exponent) + (remainder > threshold ? 1 : 0);
}
// Multiply by 2^shift in wide arithmetic, then saturate to INT32.
inline int32_t saturating_left(int32_t x, int shift) {
  const int64_t wide = static_cast<int64_t>(x) * (int64_t{1} << shift);
  return wide > INT32_MAX   ? INT32_MAX
         : wide < INT32_MIN ? INT32_MIN
                            : static_cast<int32_t>(wide);
}
// Preconditions: -31<=shift<=30, multiplier>=0, x*2^max(shift,0)
// fits INT32. The compiler proves this contract; directed tests check it.
__attribute__((noinline)) int32_t multiply(int32_t x, int32_t multiplier,
                                           int shift);
// Multiplier <= 1 path: shift is nonpositive (a right shift after high_mul).
// Kept inline so prepared constant shifts can be specialized in each caller.
inline int32_t smaller(int32_t x, int32_t multiplier, int shift) {
  return divide_pot(high_mul(x, multiplier), -shift);
}
// Multiplier > 1 path used by Softmax: left shift before high_mul.
// The caller checks/proves that the left-shifted integer fits INT32.
inline int32_t greater(int32_t x, int32_t multiplier, int shift) {
  return high_mul(x * (int32_t{1} << shift), multiplier);
}
inline int32_t clamp(int32_t x, int minimum, int maximum) {
  return x < minimum ? minimum : x > maximum ? maximum : x;
}
} // namespace arch_project::numeric
