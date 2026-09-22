#include <cstddef>
#include <cstdint>

#include "model_data.h"
#include "tensorflow/lite/core/c/common.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_log.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/system_setup.h"
#include "tensorflow/lite/schema/schema_generated.h"

#ifndef TENSOR_ARENA_SIZE
#define TENSOR_ARENA_SIZE (2 * 1024 * 1024)
#endif

namespace {

using EfficientNetOpResolver = tflite::MicroMutableOpResolver<8>;

alignas(16) std::uint8_t tensor_arena[TENSOR_ARENA_SIZE];

TfLiteStatus RegisterOps(EfficientNetOpResolver& resolver) {
  if (resolver.AddAdd() != kTfLiteOk ||
      resolver.AddAveragePool2D() != kTfLiteOk ||
      resolver.AddConv2D() != kTfLiteOk ||
      resolver.AddDepthwiseConv2D() != kTfLiteOk ||
      resolver.AddFullyConnected() != kTfLiteOk ||
      resolver.AddQuantize() != kTfLiteOk ||
      resolver.AddReshape() != kTfLiteOk ||
      resolver.AddSoftmax() != kTfLiteOk) {
    return kTfLiteError;
  }
  return kTfLiteOk;
}

void FillDeterministicInput(TfLiteTensor* input) {
  // Fixed pseudo-random bytes make native and Spike runs directly comparable.
  std::uint32_t state = 1;
  for (std::size_t index = 0; index < input->bytes; ++index) {
    state = state * 1664525u + 1013904223u;
    input->data.uint8[index] = static_cast<std::uint8_t>(state >> 24);
  }
}

std::uint32_t Fnv1a(const std::uint8_t* data, std::size_t size) {
  std::uint32_t hash = 2166136261u;
  for (std::size_t index = 0; index < size; ++index) {
    hash ^= data[index];
    hash *= 16777619u;
  }
  return hash;
}

}  // namespace

int main() {
  tflite::InitializeTarget();

  const tflite::Model* model =
      tflite::GetModel(g_efficientnet_lite0_int8_model_data);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    MicroPrintf("Schema mismatch: model=%d runtime=%d", model->version(),
                TFLITE_SCHEMA_VERSION);
    return 1;
  }

  EfficientNetOpResolver resolver;
  if (RegisterOps(resolver) != kTfLiteOk) {
    MicroPrintf("Operator registration failed");
    return 2;
  }

  tflite::MicroInterpreter interpreter(model, resolver, tensor_arena,
                                       sizeof(tensor_arena));
  if (interpreter.AllocateTensors() != kTfLiteOk) {
    MicroPrintf("AllocateTensors failed (arena=%d bytes)",
                static_cast<int>(sizeof(tensor_arena)));
    return 3;
  }

  TfLiteTensor* input = interpreter.input(0);
  TfLiteTensor* output = interpreter.output(0);
  if (input == nullptr || output == nullptr || input->type != kTfLiteUInt8 ||
      output->type != kTfLiteUInt8 || input->bytes != 224 * 224 * 3 ||
      output->bytes != 1000) {
    MicroPrintf("Unexpected model I/O contract");
    return 4;
  }

  FillDeterministicInput(input);
  if (interpreter.Invoke() != kTfLiteOk) {
    MicroPrintf("Invoke failed");
    return 5;
  }

  int top_index = 0;
  int top_score = output->data.uint8[0];
  int output_sum = 0;
  for (std::size_t index = 0; index < output->bytes; ++index) {
    const int score = output->data.uint8[index];
    output_sum += score;
    if (score > top_score) {
      top_score = score;
      top_index = static_cast<int>(index);
    }
  }

  MicroPrintf("TFLM EfficientNet-Lite0 inference: PASS");
  MicroPrintf("arena_used_bytes=%d", interpreter.arena_used_bytes());
  MicroPrintf("output_top_index=%d output_top_score=%d output_sum=%d",
              top_index, top_score, output_sum);
  MicroPrintf("output_fnv1a=0x%08x", Fnv1a(output->data.uint8, output->bytes));
  return 0;
}
