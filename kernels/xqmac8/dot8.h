// Xqmac8 v1. Packed loads are alias-safe; native builds emulate identical math.
#pragma once
#include <cstdint>
#include <type_traits>

namespace arch_project {
// The architectural result is INT32, sign-extended into an RV64 register.
// Retain that register type between instructions so GCC does not insert a
// redundant sext.w after every reduction step. Upper accumulator bits are
// ignored by both the ISA and the native emulation.
inline int64_t xqmac8_register(int64_t accumulator, uint64_t input, uint64_t weights) {
#if defined(__riscv) && __riscv_xlen == 64
  asm volatile(".insn r 0x0b, 0, 0, %0, %1, %2"
               : "+r"(accumulator) : "r"(input), "r"(weights));
  return accumulator;
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

inline int32_t xqmac8(int32_t accumulator, uint64_t input, uint64_t weights) {
  return static_cast<int32_t>(xqmac8_register(accumulator, input, weights));
}

template <int Bits>
struct Qmac8Accumulator {
  static_assert(Bits == 32 || Bits == 64);
  using Accumulator = std::conditional_t<Bits == 64, int64_t, int32_t>;
};

template <int Alignment = 1>
inline uint64_t packed8(const int8_t* input) {
  static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "Xqmac8 lane convention requires little endian");
  uint64_t result;
  static_assert(Alignment == 1 || Alignment == 2 || Alignment == 4 || Alignment == 8);
  input = static_cast<const int8_t*>(__builtin_assume_aligned(input, Alignment));
  __builtin_memcpy(&result, input, sizeof(result));
  return result;
}

template <int InputAlignment = 1, int WeightAlignment = 1, int AccumulatorBits = 32>
struct Qmac8Block : Qmac8Accumulator<AccumulatorBits> {
  using Accumulator = typename Qmac8Accumulator<AccumulatorBits>::Accumulator;
  template <int Block, int InputChannels>
  static inline void accumulate(Accumulator (&accumulator)[Block],
                                const int8_t* input, const int8_t* weights) {
    const uint64_t a = packed8<InputAlignment>(input);
#pragma GCC unroll 4
    for (int channel = 0; channel < Block; ++channel)
      accumulator[channel] = static_cast<Accumulator>(xqmac8_register(accumulator[channel], a,
                                    packed8<WeightAlignment>(weights + channel * InputChannels)));
  }
};

template <int InputAlignment = 1, int WeightAlignment = 1, int AccumulatorBits = 32>
struct Qmac8SpatialBlock : Qmac8Accumulator<AccumulatorBits> {
  using Accumulator = typename Qmac8Accumulator<AccumulatorBits>::Accumulator;
  using SinglePixel = Qmac8Block<InputAlignment, WeightAlignment, AccumulatorBits>;
  template <int Block, int InputChannels>
  static inline void accumulate(Accumulator (&accumulator)[2][Block],
                                const int8_t* input, const int8_t* weights) {
    const uint64_t a = packed8<InputAlignment>(input), b = packed8<InputAlignment>(input + InputChannels);
#pragma GCC unroll 4
    for (int channel = 0; channel < Block; ++channel) {
      const uint64_t w = packed8<WeightAlignment>(weights + channel * InputChannels);
      accumulator[0][channel] = static_cast<Accumulator>(xqmac8_register(accumulator[0][channel], a, w));
      accumulator[1][channel] = static_cast<Accumulator>(xqmac8_register(accumulator[1][channel], b, w));
    }
  }
};

template <int InputAlignment = 1, int WeightAlignment = 1, int AccumulatorBits = 32>
struct Qmac8Single : Qmac8Accumulator<AccumulatorBits> {
  using Accumulator = typename Qmac8Accumulator<AccumulatorBits>::Accumulator;
  static inline Accumulator apply(Accumulator accumulator, const int8_t* input, const int8_t* weights) {
    return static_cast<Accumulator>(xqmac8_register(accumulator, packed8<InputAlignment>(input), packed8<WeightAlignment>(weights)));
  }
};
} // namespace arch_project
