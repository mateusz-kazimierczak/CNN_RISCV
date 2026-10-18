// Xqmac8 v1. Packed loads are alias-safe; native builds emulate identical math.
#pragma once
#include <cstdint>

namespace arch_project {
inline int32_t xqmac8(int32_t accumulator, uint64_t input, uint64_t weights) {
#if defined(__riscv) && __riscv_xlen == 64
  int64_t result = accumulator;
  asm volatile(".insn r 0x0b, 0, 0, %0, %1, %2"
               : "+r"(result) : "r"(input), "r"(weights));
  return static_cast<int32_t>(result); // ISA guarantees sign-extended INT32.
#else
  uint32_t result = static_cast<uint32_t>(accumulator);
  for (unsigned lane = 0; lane < 8; ++lane) {
    const unsigned a = (input >> (8 * lane)) & 255;
    const unsigned w = (weights >> (8 * lane)) & 255;
    result += static_cast<uint32_t>((a < 128 ? int(a) : int(a) - 256) *
                                   (w < 128 ? int(w) : int(w) - 256));
  }
  return result < 0x80000000u ? static_cast<int32_t>(result)
                            : -1 - static_cast<int32_t>(~result);
#endif
}

template <int Alignment = 1>
inline uint64_t packed8(const int8_t* input) {
  static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "Xqmac8 lane convention requires little endian");
  uint64_t result;
  static_assert(Alignment == 1 || Alignment == 2 || Alignment == 4 || Alignment == 8);
  input = static_cast<const int8_t*>(__builtin_assume_aligned(input, Alignment));
  __builtin_memcpy(&result, input, sizeof(result));
  return result;
}

template <int InputAlignment = 1, int WeightAlignment = 1>
struct Qmac8Block {
  template <int Block, int InputChannels>
  static inline void accumulate(int32_t (&accumulator)[Block],
                                const int8_t* input, const int8_t* weights) {
    const uint64_t a = packed8<InputAlignment>(input);
#pragma GCC unroll 4
    for (int channel = 0; channel < Block; ++channel)
      accumulator[channel] = xqmac8(accumulator[channel], a,
                                    packed8<WeightAlignment>(weights + channel * InputChannels));
  }
};

template <int InputAlignment = 1, int WeightAlignment = 1>
struct Qmac8SpatialBlock {
  using SinglePixel = Qmac8Block<InputAlignment, WeightAlignment>;
  template <int Block, int InputChannels>
  static inline void accumulate(int32_t (&accumulator)[2][Block],
                                const int8_t* input, const int8_t* weights) {
    const uint64_t a = packed8<InputAlignment>(input), b = packed8<InputAlignment>(input + InputChannels);
#pragma GCC unroll 4
    for (int channel = 0; channel < Block; ++channel) {
      const uint64_t w = packed8<WeightAlignment>(weights + channel * InputChannels);
      accumulator[0][channel] = xqmac8(accumulator[0][channel], a, w);
      accumulator[1][channel] = xqmac8(accumulator[1][channel], b, w);
    }
  }
};

template <int InputAlignment = 1, int WeightAlignment = 1>
struct Qmac8Single {
  static inline int32_t apply(int32_t accumulator, const int8_t* input, const int8_t* weights) {
    return xqmac8(accumulator, packed8<InputAlignment>(input), packed8<WeightAlignment>(weights));
  }
};
} // namespace arch_project
