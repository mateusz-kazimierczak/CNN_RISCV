#pragma once
#include "memory.h"
#include "kernels/xqmac8/dot8.h"

namespace arch_project {
template <int InputAlignment, int WeightAlignment, int AccumulatorBits = 64>
struct Qmac8PostincBlock : Qmac8Block<InputAlignment, WeightAlignment, AccumulatorBits> {
  using Accumulator = typename Qmac8Accumulator<AccumulatorBits>::Accumulator;
  template <int Block, int InputChannels>
  static inline void accumulate_postinc(Accumulator (&accumulator)[Block],
      const int8_t*& input, const int8_t*& weights) {
    static_assert(InputAlignment == 8 && WeightAlignment == 8);
    const uint64_t a = postinc::load<uint64_t, 8>(input);
    const uint64_t w0 = postinc::load<uint64_t, 8>(weights);
#pragma GCC unroll 4
    for (int ch = 0; ch < Block; ++ch) {
      const uint64_t w = ch == 0 ? w0 : packed8<8>(weights + ch * InputChannels - 8);
      accumulator[ch] = static_cast<Accumulator>(xqmac8_register(accumulator[ch], a, w));
    }
  }
};
template <int InputAlignment, int WeightAlignment, int AccumulatorBits = 64>
struct Qmac8PostincSpatialBlock : Qmac8SpatialBlock<InputAlignment, WeightAlignment, AccumulatorBits> {
  using Accumulator = typename Qmac8Accumulator<AccumulatorBits>::Accumulator;
  using SinglePixel = Qmac8PostincBlock<InputAlignment, WeightAlignment, AccumulatorBits>;
  template <int Block, int InputChannels>
  static inline void accumulate_postinc(Accumulator (&accumulator)[2][Block],
      const int8_t*& input, const int8_t*& weights) {
    static_assert(InputAlignment == 8 && WeightAlignment == 8);
    const uint64_t a = postinc::load<uint64_t, 8>(input);
    const uint64_t b = packed8<8>(input + InputChannels - 8);
    const uint64_t w0 = postinc::load<uint64_t, 8>(weights);
#pragma GCC unroll 4
    for (int ch = 0; ch < Block; ++ch) {
      const uint64_t w = ch == 0 ? w0 : packed8<8>(weights + ch * InputChannels - 8);
      accumulator[0][ch] = static_cast<Accumulator>(xqmac8_register(accumulator[0][ch], a, w));
      accumulator[1][ch] = static_cast<Accumulator>(xqmac8_register(accumulator[1][ch], b, w));
    }
  }
};
}  // namespace arch_project
