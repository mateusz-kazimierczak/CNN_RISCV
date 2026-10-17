#pragma once
#include <cstdint>
namespace arch_project::numeric {
// Q5.26 -> Q0.31 exponential, and normalized reciprocal. Scalar ports of the
// pinned gemmlowp routines, exposed here for independent differential tests.
int32_t exp_negative_q5(int32_t x);
int32_t reciprocal(int32_t x, int integer_bits, int *exponent_bits);
// Status 1: invalid/range error; 2: pinned output-exponent limitation.
// Error leaves output untouched. sum/exponent preserve the diagnostic ABI.
int softmax(const int8_t *input, int depth, int32_t multiplier, int left_shift,
            int diff_min, int8_t *output, int32_t *sum_raw, int *exponent);
} // namespace arch_project::numeric
