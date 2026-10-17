// Host-only reference capture. Never linked into the measured B0 executable.
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "model_data.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/micro_profiler_interface.h"
#include "tensorflow/lite/micro/system_setup.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/schema/schema_utils.h"

namespace {

// Host debugging capacity only; this is not a target memory requirement.
alignas(16) std::uint8_t arena[16 * 1024 * 1024];
constexpr std::size_t kInputBytes = 224 * 224 * 3;

bool WriteBytes(const char* directory, const char* name, const void* data,
                std::size_t size) {
  char path[4096];
  const int count = std::snprintf(path, sizeof(path), "%s/%s", directory, name);
  if (count < 0 || static_cast<std::size_t>(count) >= sizeof(path)) return false;
  std::FILE* file = std::fopen(path, "wb");
  if (file == nullptr) return false;
  const bool written = std::fwrite(data, 1, size, file) == size;
  const bool closed = std::fclose(file) == 0;
  return written && closed;
}

class TensorCapture final : public tflite::MicroProfilerInterface {
 public:
  TensorCapture(const tflite::Model* model, const char* directory, std::FILE* table)
      : model_(model), directory_(directory), table_(table) {}

  tflite::MicroInterpreter* interpreter = nullptr;
  bool ok = true;
  std::uint32_t started = 0;
  std::uint32_t finished = 0;

  std::uint32_t BeginEvent(const char* tag) override {
    const std::uint32_t node_index = started++;
    const auto* graph = model_->subgraphs()->Get(0);
    if (node_index >= graph->operators()->size()) {
      ok = false;
      return node_index;
    }
    const auto* op = graph->operators()->Get(node_index);
    const auto code = tflite::GetBuiltinCode(model_->operator_codes()->Get(op->opcode_index()));
    if (std::strcmp(tag, tflite::EnumNameBuiltinOperator(code)) != 0) {
      std::fprintf(stderr, "Node %u callback mismatch: %s != %s\n", node_index,
                   tag, tflite::EnumNameBuiltinOperator(code));
      ok = false;
    }
    return node_index;
  }

  void EndEvent(std::uint32_t node_index) override {
    const auto* graph = model_->subgraphs()->Get(0);
    if (!ok || interpreter == nullptr || node_index != finished ||
        node_index >= graph->operators()->size()) {
      ok = false;
      return;
    }
    const auto* op = graph->operators()->Get(node_index);
    const auto code = tflite::GetBuiltinCode(model_->operator_codes()->Get(op->opcode_index()));
    for (std::uint32_t slot = 0; slot < op->outputs()->size(); ++slot) {
      const int tensor_index = op->outputs()->Get(slot);
      const auto* tensor = interpreter->GetTensor(tensor_index);
      if (tensor == nullptr || tensor->dims == nullptr ||
          (tensor->type != kTfLiteInt8 && tensor->type != kTfLiteUInt8)) {
        ok = false;
        return;
      }
      std::size_t bytes = 1;
      for (int dim = 0; dim < tensor->dims->size; ++dim) {
        const int size = tensor->dims->data[dim];
        if (size <= 0 || bytes > sizeof(arena) / static_cast<std::size_t>(size)) {
          ok = false;
          return;
        }
        bytes *= static_cast<std::size_t>(size);
      }
      char name[96];
      std::snprintf(name, sizeof(name), "node_%02u_output_%u_tensor_%03d.bin",
                    node_index, slot, tensor_index);
      if (!WriteBytes(directory_, name, tensor->data.raw, bytes)) {
        ok = false;
        return;
      }
      std::fprintf(table_, "%u\t%d\t%u\t%s\t%s\t%zu\t", node_index,
                   tensor_index, slot, tflite::EnumNameBuiltinOperator(code),
                   tensor->type == kTfLiteInt8 ? "INT8" : "UINT8", bytes);
      for (int dim = 0; dim < tensor->dims->size; ++dim) {
        std::fprintf(table_, "%s%d", dim == 0 ? "" : ",", tensor->dims->data[dim]);
      }
      std::fprintf(table_, "\t%s\n", name);
    }
    // Keep completed tensors diagnosable even if a later reference kernel aborts.
    if (std::fflush(table_) != 0) ok = false;
    ++finished;
  }

 private:
  const tflite::Model* model_;
  const char* directory_;
  std::FILE* table_;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3 && (argc != 4 || std::strcmp(argv[3], "--no-preserve") != 0)) {
    std::fprintf(stderr, "usage: compiler_tflm_oracle INPUT.bin|- OUTPUT_DIRECTORY [--no-preserve]\n");
    return 1;
  }
  const bool preserve = argc == 3;
  tflite::InitializeTarget();
  const auto* model = tflite::GetModel(g_efficientnet_lite0_int8_model_data);
  if (model->version() != TFLITE_SCHEMA_VERSION || model->subgraphs()->size() != 1 ||
      model->subgraphs()->Get(0)->operators()->size() != 64) return 2;

  tflite::MicroMutableOpResolver<8> resolver;
  if (resolver.AddAdd() != kTfLiteOk || resolver.AddAveragePool2D() != kTfLiteOk ||
      resolver.AddConv2D() != kTfLiteOk || resolver.AddDepthwiseConv2D() != kTfLiteOk ||
      resolver.AddFullyConnected() != kTfLiteOk || resolver.AddQuantize() != kTfLiteOk ||
      resolver.AddReshape() != kTfLiteOk || resolver.AddSoftmax() != kTfLiteOk) return 3;

  char table_path[4096];
  const int count = std::snprintf(table_path, sizeof(table_path), "%s/tensors.tsv", argv[2]);
  if (count < 0 || static_cast<std::size_t>(count) >= sizeof(table_path)) return 4;
  std::FILE* table = std::fopen(table_path, "w");
  if (table == nullptr) return 4;
  std::fprintf(table, "node\ttensor\tslot\toperator\ttype\tbytes\tshape\tfile\n");
  TensorCapture capture(model, argv[2], table);
  tflite::MicroInterpreter interpreter(
      model, resolver, arena, preserve ? sizeof(arena) : 2 * 1024 * 1024,
      nullptr, preserve ? &capture : nullptr, preserve);
  capture.interpreter = &interpreter;
  if (interpreter.AllocateTensors() != kTfLiteOk ||
      interpreter.preserve_all_tensors() != preserve) {
    std::fclose(table);
    return 5;
  }
  auto* input = interpreter.input(0);
  auto* output = interpreter.output(0);
  if (input == nullptr || input->type != kTfLiteUInt8 || input->bytes != kInputBytes ||
      output == nullptr || output->type != kTfLiteUInt8 || output->bytes != 1000) {
    std::fclose(table);
    return 6;
  }
  if (std::strcmp(argv[1], "-") == 0) {
    // Independent C++ reproduction of the unchanged B0 application's sequence.
    std::uint32_t state = 1;
    for (std::size_t index = 0; index < input->bytes; ++index) {
      state = state * 1664525u + 1013904223u;
      input->data.uint8[index] = static_cast<std::uint8_t>(state >> 24);
    }
  } else {
    std::FILE* file = std::fopen(argv[1], "rb");
    if (file == nullptr) {
      std::fclose(table);
      return 7;
    }
    const bool read = std::fread(input->data.uint8, 1, input->bytes, file) == input->bytes;
    const bool exact = std::fgetc(file) == EOF && !std::ferror(file);
    const bool closed = std::fclose(file) == 0;
    if (!read || !exact || !closed) {
      std::fclose(table);
      return 7;
    }
  }
  if (!WriteBytes(argv[2], "input.bin", input->data.raw, input->bytes)) {
    std::fclose(table);
    return 8;
  }
  const auto status = interpreter.Invoke();
  const bool table_ok = std::ferror(table) == 0;
  const bool closed = std::fclose(table) == 0;
  if (status != kTfLiteOk || (preserve && (!capture.ok || capture.started != 64 ||
      capture.finished != 64)) || !table_ok || !closed) {
    std::fprintf(stderr, "Incomplete oracle: status=%d started=%u finished=%u capture_ok=%d\n",
                 status, capture.started, capture.finished, capture.ok);
    return 9;
  }
  if (!WriteBytes(argv[2], "output.bin", output->data.raw, output->bytes)) return 10;
  std::printf("Completed inference; captured_nodes=%u; preserve_all_tensors=%s; arena_used_bytes=%zu\n",
               capture.finished, preserve ? "true" : "false", interpreter.arena_used_bytes());
  return 0;
}
