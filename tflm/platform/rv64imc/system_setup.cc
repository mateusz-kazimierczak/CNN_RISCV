#include "tensorflow/lite/micro/system_setup.h"

namespace tflite {

// crt0.S provides the current target setup. A hardware port can initialize
// board-specific peripherals here before model preparation.
void InitializeTarget() {}

}  // namespace tflite
