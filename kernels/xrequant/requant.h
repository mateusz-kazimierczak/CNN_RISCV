// Xrequant v1: exact double rounding; low INT32 source; sign-extended result.
#pragma once
#include <cstdint>
namespace arch_project {
constexpr uint64_t requant_descriptor(int32_t multiplier, int shift, int zero,
                                      int minimum, int maximum, bool scale = false) {
  return uint32_t(multiplier) | (uint64_t(-shift) << 32) |
      (uint64_t(uint8_t(zero)) << 38) | (uint64_t(uint8_t(minimum)) << 46) |
      (uint64_t(uint8_t(maximum)) << 54) | (uint64_t(scale) << 62);
}
inline int64_t xrequant(int64_t accumulator, uint64_t descriptor) {
#if defined(__riscv) && __riscv_xlen == 64
  int64_t result;
  asm volatile(".insn r 0x0b, 1, 0, %0, %1, %2"
               : "=r"(result) : "r"(accumulator), "r"(descriptor));
  return result;
#else
  const uint32_t m = uint32_t(descriptor);
  const unsigned r = (descriptor >> 32) & 63;
  const int z = int8_t(descriptor >> 38), lo = int8_t(descriptor >> 46), hi = int8_t(descriptor >> 54);
  const bool scale = (descriptor >> 62) & 1;
  if ((descriptor >> 63) || m > 0x7fffffffu || r > 31 || lo > hi ||
      (scale && (z || lo || hi))) __builtin_trap();
  const uint32_t low = uint32_t(accumulator);
  const int64_t x = low < 0x80000000u ? int64_t(low) : int64_t(low) - (int64_t(1) << 32);
  const int64_t high = (x * m + (int64_t(1) << 30)) >> 31;
  const uint32_t mask = uint32_t((uint64_t(1) << r) - 1);
  const uint32_t remainder = uint32_t(high) & mask;
  const uint32_t threshold = (mask >> 1) + (high < 0);
  const int64_t scaled = (high >> r) + (remainder > threshold);
  const int64_t biased = scaled + z;
  return scale ? scaled : biased < lo ? lo : biased > hi ? hi : biased;
#endif
}
struct XRequantization {
  static constexpr bool packed_output = true;
  static inline uint64_t load(const int32_t* words, int channel) {
    uint64_t result;
    const auto* p = static_cast<const int32_t*>(__builtin_assume_aligned(words, 8));
    __builtin_memcpy(&result, p + 2 * channel, 8);
    return result;
  }
  static inline int64_t finish(int64_t x, uint64_t descriptor) { return xrequant(x, descriptor); }
  static inline int32_t scale(int32_t x, int32_t m, int shift) {
    return int32_t(xrequant(x, requant_descriptor(m, shift, 0, 0, 0, true)));
  }
  static inline int64_t output(int32_t x, int32_t m, int shift, int z, int lo, int hi) {
    return xrequant(x, requant_descriptor(m, shift, z, lo, hi));
  }
};
} // namespace arch_project
