// Exercise the same translation units under ASan/UBSan, including reference
// inline helpers. Assertions are enabled here (unlike release B0).
#include "../../kernels/reference/numerics.h"
#include <cassert>
#include <cstdint>
#include <cstdio>

int main() {
  uint32_t state = 42;
  int32_t out = 123;
  for (int shift = -31; shift <= 30; ++shift) {
    for (int i = 0; i < 1000; ++i) {
      state = state * 1664525u + 1013904223u;
      const int32_t magnitude = static_cast<int32_t>((state >> 1) >> (shift > 0 ? shift : 0));
      const int32_t x = i % 2 ? -magnitude : magnitude;
      assert(cc_requantize(x, 1073741824, shift, &out) == 0);
    }
  }
  assert(cc_requantize(INT32_MAX, INT32_MAX, 1, &out) == 1);
  int8_t input[1000], result[1000];
  int32_t sum; int exponent;
  for (int mode = 0; mode < 20; ++mode) {
    for (int i = 0; i < 1000; ++i) input[i] = static_cast<int8_t>((i * (mode + 1) % 256) - 128);
    const int status = cc_softmax(input, 1000, 1073741824, 27, -15, result, &sum, &exponent);
    assert(status == 0 || status == 2);
  }
  for (int i = 0; i < 1000; ++i) input[i] = 0;
  assert(cc_softmax(input, 1000, 1073741824, 27, -15, result, &sum, &exponent) == 2);
  assert(exponent == 32);
  assert(cc_pool(input, 1000, -128, 127, &out) == 0);
  for (int i = 0; i < 1000; ++i) input[i] = -128;
  assert(cc_pool(input, 1000, -128, 127, &out) == 0 && out == -128);
  assert(cc_dot(input, input, 1000, 128, 11, &out) == 0 && out == 11);
  const int32_t p[] = {9, -7, 0, 1073741824, 1073741824, 1073741824, 0, -1, -18, 20, -128, 127};
  for (int x = -128; x <= 127; ++x)
    for (int y = -128; y <= 127; ++y) assert(cc_add(x, y, p, &out) == 0);
  uint8_t bytes[256], shifted[256];
  for (int i = 0; i < 256; ++i) bytes[i] = static_cast<uint8_t>(i);
  assert(cc_boundary(bytes, 256, true, shifted) == 0);
  for (int i = 0; i < 256; ++i) assert(shifted[i] == (i ^ 128));
  assert(cc_boundary(shifted, 256, false, bytes) == 0);
  int8_t pixels[] = {-9, -8, -7, -6}, weights[] = {1, 2, 3, 4, 5, 6, 7, 8, 9};
  int8_t border[4];
  assert(cc_conv_border(pixels, weights, 9, nullptr, border) == 0);
  assert(border[0] == 49);
  std::puts("ASan/UBSan numeric helpers: PASS (62000 requantizations, 65536 ADD pairs, Softmax/pool/dot/boundaries)");
}
