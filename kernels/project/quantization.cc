#include "quantization.h"
namespace arch_project::numeric {
int32_t multiply(int32_t x, int32_t multiplier, int shift) {
  const int left = shift > 0 ? shift : 0;
  const int right = shift > 0 ? 0 : -shift;
  return divide_pot(high_mul(x * (1 << left), multiplier), right);
}
} // namespace arch_project::numeric
