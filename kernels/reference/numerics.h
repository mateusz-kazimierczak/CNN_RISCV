// Standalone numeric helpers only: no interpreter, tensor allocator or graph.
#ifndef ARCH_PROJECT_REFERENCE_NUMERICS_H_
#define ARCH_PROJECT_REFERENCE_NUMERICS_H_
#include <cstdint>

extern "C" {
// Return 0 on success, 1 for invalid/overflowing arguments, 2 for the pinned
// Softmax exponent limitation. Rejection leaves output untouched.
int cc_requantize(int32_t x, int32_t multiplier, int shift, int32_t* output);
int cc_softmax(const int8_t* input, int depth, int32_t multiplier,
               int left_shift, int diff_min, int8_t* output,
               int32_t* sum_raw, int* exponent);
// ADD params: offsets[3], multipliers[3], shifts[3], left_shift, clamp[2].
int cc_add(int x, int y, const int32_t* params, int32_t* output);
int cc_pool(const int8_t* input, int count, int minimum, int maximum, int32_t* output);
int cc_dot(const int8_t* input, const int8_t* weights, int count,
           int input_offset, int32_t bias, int32_t* output);
int cc_boundary(const uint8_t* input, int count, bool to_signed, uint8_t* output);
// Directed test adapter: 2x2 NHWC input, 3x3 OHWI filter, SAME pad=1,
// one channel, identity requantization, optional bias, full INT8 clamp.
int cc_conv_border(const int8_t* input, const int8_t* weights,
                   int input_offset, const int32_t* bias, int8_t* output);
}
#endif
