// Reuse the pinned reference functions; range-check before entering them.
#include "numerics.h"
#include <algorithm>
#include <limits>
#include <cstring>
#include "tensorflow/lite/kernels/internal/common.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/add.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/conv.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/fully_connected.h"
#include "tensorflow/lite/kernels/internal/reference/integer_ops/pooling.h"
#include "tensorflow/lite/kernels/internal/reference/requantize.h"
#include "tensorflow/lite/kernels/internal/reference/softmax.h"

#if TFLITE_SINGLE_ROUNDING || defined(TFLITE_EMULATE_FLOAT)
#error "Stage 2 contract requires the B0 double-rounding, IEEE preparation configuration"
#endif
static_assert((-3 >> 1) == -2, "Pinned C++17 helpers require arithmetic right shifts");
static_assert(sizeof(int32_t) == 4 && sizeof(int8_t) == 1, "Exact-width integers required");
namespace {
bool Fits(int64_t x) { return x >= INT32_MIN && x <= INT32_MAX; }
bool Int8(int x) { return x >= -128 && x <= 127; }
bool Scale(int32_t x, int32_t multiplier, int shift) {
  return multiplier >= 0 && shift >= -31 && shift <= 30 &&
         Fits(static_cast<int64_t>(x) * (int64_t{1} << std::max(0, shift)));
}
}  // namespace

extern "C" int cc_requantize(int32_t x, int32_t multiplier, int shift, int32_t* output) {
  if (!output || !Scale(x, multiplier, shift)) return 1;
  *output = tflite::MultiplyByQuantizedMultiplier(x, multiplier, shift);
  return 0;
}

extern "C" int cc_softmax(const int8_t* input, int depth, int32_t multiplier,
                           int left_shift, int diff_min, int8_t* output,
                           int32_t* sum_raw, int* exponent) {
  if (!input || !output || !sum_raw || !exponent || depth <= 0 || depth > 1000 ||
      left_shift < 0 || left_shift > 30 || multiplier <= 0 || diff_min > 0) return 1;
  const int maximum = *std::max_element(input, input + depth);
  using Diff = gemmlowp::FixedPoint<int32_t, 5>;
  // This is a diagnostic preflight of the reference's accumulation, not a
  // replacement Softmax. It prevents the known abort and records its cause.
  int64_t sum = 0;
  for (int i = 0; i < depth; ++i) {
    const int diff = input[i] - maximum;
    if (diff >= diff_min) {
      if (!Scale(diff, multiplier, left_shift)) return 1;
      const int32_t scaled = tflite::MultiplyByQuantizedMultiplierGreaterThanOne(
          diff, multiplier, left_shift);
      sum += gemmlowp::Rescale<12>(gemmlowp::exp_on_negative_values(Diff::FromRaw(scaled))).raw();
    }
  }
  if (sum <= 0 || !Fits(sum)) return 1;
  *sum_raw = static_cast<int32_t>(sum);
  int bits;
  (void)tflite::GetReciprocal(*sum_raw, 12, &bits);
  *exponent = bits + 31 - 8;
  if (*exponent < 0 || *exponent > 31) return 2;
  tflite::SoftmaxParams params{};
  params.input_multiplier = multiplier;
  params.input_left_shift = left_shift;
  params.diff_min = diff_min;
  const int32_t dims[] = {1, depth};
  tflite::RuntimeShape shape(2, dims);
  tflite::reference_ops::Softmax(params, shape, input, shape, output);
  return 0;
}

extern "C" int cc_add(int x, int y, const int32_t* p, int32_t* output) {
  if (!p || !output || !Int8(x) || !Int8(y) || p[9] != 20 ||
      p[10] < -128 || p[11] > 127 || p[10] > p[11] ||
      p[0] < -127 || p[0] > 128 || p[1] < -127 || p[1] > 128 || !Int8(p[2])) return 1;
  int32_t a, b, result;
  if (p[6] > 0 || p[7] > 0 || p[8] > 0 ||
      cc_requantize((x + p[0]) * (1 << 20), p[3], p[6], &a) ||
      cc_requantize((y + p[1]) * (1 << 20), p[4], p[7], &b) ||
      !Fits(static_cast<int64_t>(a) + b) ||
      cc_requantize(a + b, p[5], p[8], &result) || !Fits(static_cast<int64_t>(result) + p[2])) return 1;
  tflite::ArithmeticParams params{};
  params.input1_offset = p[0]; params.input2_offset = p[1]; params.output_offset = p[2];
  params.input1_multiplier = p[3]; params.input2_multiplier = p[4]; params.output_multiplier = p[5];
  params.input1_shift = p[6]; params.input2_shift = p[7]; params.output_shift = p[8];
  params.left_shift = p[9]; params.quantized_activation_min = p[10]; params.quantized_activation_max = p[11];
  *output = tflite::reference_integer_ops::AddFunc(static_cast<int8_t>(x), static_cast<int8_t>(y), params);
  return 0;
}

extern "C" int cc_pool(const int8_t* input, int count, int minimum, int maximum, int32_t* output) {
  if (!input || !output || count <= 0 || count > 1000000 ||
      !Int8(minimum) || !Int8(maximum) || minimum > maximum) return 1;
  tflite::PoolParams p{};
  p.stride_height = p.stride_width = 1; p.filter_height = 1; p.filter_width = count;
  p.quantized_activation_min = minimum; p.quantized_activation_max = maximum;
  const int32_t in_dims[] = {1, 1, count, 1}, out_dims[] = {1, 1, 1, 1};
  int8_t result;
  if (!tflite::reference_integer_ops::AveragePool(p, tflite::RuntimeShape(4, in_dims),
        input, tflite::RuntimeShape(4, out_dims), &result)) return 1;
  *output = result;
  return 0;
}

extern "C" int cc_dot(const int8_t* input, const int8_t* weights, int count,
                       int input_offset, int32_t bias, int32_t* output) {
  if (!input || !weights || !output || count <= 0 || count > 1000000 ||
      input_offset < -127 || input_offset > 128) return 1;
  int64_t accumulator = 0;
  for (int i = 0; i < count; ++i) {
    accumulator += (static_cast<int>(input[i]) + input_offset) * static_cast<int>(weights[i]);
    if (!Fits(accumulator)) return 1;
  }
  accumulator += bias;
  if (!Fits(accumulator)) return 1;
  // Return raw accumulator for independent dot/adjusted-bias proofs. All
  // additions are wide above; no signed wrapping semantics are assumed.
  *output = static_cast<int32_t>(accumulator);
  return 0;
}

extern "C" int cc_boundary(const uint8_t* input, int count, bool to_signed, uint8_t* output) {
  if (!input || !output || count < 0) return 1;
  for (int i = 0; i < count; ++i) {
    if (to_signed) {
      int8_t result;
      tflite::reference_ops::Requantize(input + i, 1, 1 << 30, 1, 131, 3, &result);
      std::memcpy(output + i, &result, 1);
    } else {
      int8_t value;
      std::memcpy(&value, input + i, 1);
      tflite::reference_ops::Requantize(&value, 1, 1 << 30, 1, -128, 0, output + i);
    }
  }
  return 0;
}

extern "C" int cc_conv_border(const int8_t* input, const int8_t* weights,
                               int input_offset, const int32_t* bias, int8_t* output) {
  if (!input || !weights || !output || input_offset < -127 || input_offset > 128 ||
      (bias && (*bias < -100000000 || *bias > 100000000))) return 1;
  tflite::ConvParams p{};
  p.input_offset = input_offset;
  p.stride_height = p.stride_width = p.dilation_height_factor = p.dilation_width_factor = 1;
  p.padding_values.height = p.padding_values.width = 1;
  p.quantized_activation_min = -128; p.quantized_activation_max = 127;
  const int32_t dims[] = {1, 2, 2, 1}, filter[] = {1, 3, 3, 1}, bias_dims[] = {1};
  const int32_t multiplier[] = {1 << 30}, shift[] = {1};
  tflite::reference_integer_ops::ConvPerChannel(p, multiplier, shift,
      tflite::RuntimeShape(4, dims), input, tflite::RuntimeShape(4, filter), weights,
      tflite::RuntimeShape(1, bias_dims), bias, tflite::RuntimeShape(4, dims), output);
  return 0;
}
