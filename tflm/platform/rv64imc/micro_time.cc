#include "tensorflow/lite/micro/micro_time.h"

#include <cstdint>

namespace tflite {

// Timing is deliberately disabled for the first functional port. Spike
// instruction counts will be collected independently.
std::uint32_t ticks_per_second() { return 0; }
std::uint32_t GetCurrentTimeTicks() { return 0; }

}  // namespace tflite
