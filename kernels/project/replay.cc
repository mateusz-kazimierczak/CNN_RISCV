// Test-only scalar replay reference; same checked int64 path as cc_dot.
#include "numerics.h"
extern "C" int cc_dot(const int8_t *input, const int8_t *weights, int count,
                      int input_offset, int32_t bias, int32_t *output) {
  if (!input || !weights || !output || count <= 0 || count > 1000000 ||
      input_offset < -127 || input_offset > 128)
    return 1;
  int64_t accumulator = 0;
  for (int i = 0; i < count; ++i) {
    accumulator += (static_cast<int>(input[i]) + input_offset) *
                   static_cast<int>(weights[i]);
    if ((accumulator < INT32_MIN || accumulator > INT32_MAX))
      return 1;
  }
  accumulator += bias;
  if ((accumulator < INT32_MIN || accumulator > INT32_MAX))
    return 1;
  // Return raw accumulator for independent dot/adjusted-bias proofs. All
  // additions are wide above; no signed wrapping semantics are assumed.
  *output = static_cast<int32_t>(accumulator);
  return 0;
}
