// Register-storage policy only. The compiler proves shifted INT8 inputs and
// the sum of the two scaled results fit INT32 before selecting this policy.
#pragma once
#include "kernels/xrequant/requant.h"

namespace arch_project {
struct XRequantization64 : XRequantization {
  static inline int64_t scale(int64_t x, int32_t m, int shift) {
    return xrequant(x, requant_descriptor(m, shift, 0, 0, 0, true));
  }
  static inline int64_t output(int64_t x, int32_t m, int shift, int z, int lo,
                               int hi) {
    return xrequant(x, requant_descriptor(m, shift, z, lo, hi));
  }
};
} // namespace arch_project
