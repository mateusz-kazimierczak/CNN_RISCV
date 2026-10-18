// Exercise all reduction schedules with identical scalar quantization policies.
#define ARCH_PROJECT_PROJECT_NUMERICS 1
#include "kernels/project/quantization.h"
#include "kernels/rv64imc/pointwise.h"
#include "kernels/xqmac8/dot8.h"

static uint32_t random_state = 0x3c42b817;
static uint32_t next_word() {
  random_state = random_state * 1664525u + 1013904223u;
  return random_state;
}

template <int Pixels, int K, int C>
bool check_schedules() {
  int8_t input[Pixels * K], weights[C * K], expected[Pixels * C], actual[Pixels * C + 2];
  int32_t biases[C], multipliers[C], shifts[C];
  for (int trial = 0; trial < 12; ++trial) {
    for (auto &x : input) x = static_cast<int8_t>(next_word() >> 24);
    for (auto &w : weights) w = static_cast<int8_t>(next_word() >> 24);
    for (int c = 0; c < C; ++c) {
      biases[c] = static_cast<int32_t>(next_word() % 200001) - 100000;
      multipliers[c] = 0x40000000 + (next_word() & 0x3fffffff);
      shifts[c] = -static_cast<int>(next_word() % 32);
    }
    using Policy = arch_project::numeric::InlineNonpositiveRequantization;
    arch_project::pointwise_dot8<Pixels, K, C, -7, -80, 100, Policy>(
        input, weights, biases, multipliers, shifts, expected);
    auto reset = [&]() {
      for (auto &x : actual) x = 57;
    };
    auto matches = [&]() {
      if (actual[0] != 57 || actual[Pixels * C + 1] != 57) return false;
      for (int i = 0; i < Pixels * C; ++i)
        if (actual[i + 1] != expected[i]) return false;
      return true;
    };
    reset();
    arch_project::pointwise_dot8<Pixels, K, C, -7, -80, 100, Policy,
        arch_project::Qmac8Single<1, 1, 64>>(
        input, weights, biases, multipliers, shifts, actual + 1);
    if (!matches()) return false;
#define CHECK(BLOCK) \
    reset(); \
    arch_project::pointwise_dot8_blocked<Pixels, K, C, -7, -80, 100, BLOCK, \
        arch_project::Qmac8Block<1, 1, 64>, Policy>( \
        input, weights, biases, multipliers, shifts, actual + 1); \
    if (!matches()) return false; \
    reset(); \
    arch_project::pointwise_dot8_spatial2<Pixels, K, C, -7, -80, 100, BLOCK, \
        arch_project::Qmac8SpatialBlock<1, 1, 64>, Policy>( \
        input, weights, biases, multipliers, shifts, actual + 1); \
    if (!matches()) return false
    if constexpr (C % 2 == 0) { CHECK(2); }
    if constexpr (C % 4 == 0) { CHECK(4); }
#undef CHECK
  }
  return true;
}

static bool check_all_schedules() {
  return check_schedules<1, 8, 1>() && check_schedules<1, 16, 4>() &&
         check_schedules<2, 8, 4>() && check_schedules<3, 24, 8>() &&
         check_schedules<4, 32, 6>() && check_schedules<49, 320, 4>();
}
