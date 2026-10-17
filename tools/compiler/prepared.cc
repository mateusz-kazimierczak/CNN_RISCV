// Host-only oracle: observe actual pinned Prepare results, without invoking.
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/kernels/add.h"
#include "tensorflow/lite/micro/kernels/conv.h"
#include "tensorflow/lite/micro/kernels/fully_connected.h"
#include "tensorflow/lite/micro/kernels/pooling.h"
#include "tensorflow/lite/micro/kernels/quantize.h"
#include "tensorflow/lite/schema/schema_utils.h"

namespace {
alignas(16) std::uint8_t arena[16 * 1024 * 1024];
TFLMRegistration originals[128];
const tflite::Model* model;
std::FILE* output;
unsigned next_node = 0;

void Field(const char* name, int value) {
  std::fprintf(output, "\"%s\":%d,", name, value);
}
void Array(const char* name, const int32_t* data, int count) {
  std::fprintf(output, "\"%s\":[", name);
  for (int i = 0; i < count; ++i) std::fprintf(output, "%s%d", i ? "," : "", data[i]);
  std::fprintf(output, "],");
}
#define FIELD(data, name) Field(#name, (data).name)
template <int Code>
TfLiteStatus Prepare(TfLiteContext* context, TfLiteNode* node) {
  const auto* op = model->subgraphs()->Get(0)->operators()->Get(next_node);
  if (tflite::GetBuiltinCode(model->operator_codes()->Get(op->opcode_index())) != Code)
    return kTfLiteError;
  if (originals[Code].prepare != nullptr &&
      originals[Code].prepare(context, node) != kTfLiteOk) return kTfLiteError;
  std::fprintf(output, "%s{\"node\":%u,\"kind\":\"%s\",\"integers\":{",
               next_node ? ",\n" : "", next_node, tflite::EnumNameBuiltinOperator(
                   static_cast<tflite::BuiltinOperator>(Code)));
  if (Code == tflite::BuiltinOperator_CONV_2D || Code == tflite::BuiltinOperator_DEPTHWISE_CONV_2D) {
    const auto& d = *static_cast<const tflite::OpDataConv*>(node->user_data);
    FIELD(d, input_zero_point); FIELD(d, filter_zero_point); FIELD(d, output_zero_point);
    FIELD(d, output_activation_min); FIELD(d, output_activation_max);
    Field("padding_height", d.padding.height); Field("padding_width", d.padding.width);
    Field("padding_height_offset", d.padding.height_offset);
    Field("padding_width_offset", d.padding.width_offset);
    const auto* weights = model->subgraphs()->Get(0)->tensors()->Get(node->inputs->data[1]);
    const int channels = weights->shape()->Get(Code == tflite::BuiltinOperator_CONV_2D ? 0 : 3);
    Array("multipliers", d.per_channel_output_multiplier, channels);
    Array("shifts", d.per_channel_output_shift, channels);
  } else if (Code == tflite::BuiltinOperator_FULLY_CONNECTED) {
    const auto& d = *static_cast<const tflite::OpDataFullyConnected*>(node->user_data);
    FIELD(d, input_zero_point); FIELD(d, filter_zero_point); FIELD(d, output_zero_point);
    FIELD(d, output_activation_min); FIELD(d, output_activation_max);
    FIELD(d, output_multiplier); FIELD(d, output_shift);
  } else if (Code == tflite::BuiltinOperator_ADD) {
    const auto& d = *static_cast<const tflite::OpDataAdd*>(node->user_data);
    FIELD(d, requires_broadcast); FIELD(d, left_shift);
    FIELD(d, input1_offset); FIELD(d, input2_offset); FIELD(d, output_offset);
    FIELD(d, input1_multiplier); FIELD(d, input2_multiplier); FIELD(d, output_multiplier);
    FIELD(d, input1_shift); FIELD(d, input2_shift); FIELD(d, output_shift);
    FIELD(d, output_activation_min); FIELD(d, output_activation_max);
  } else if (Code == tflite::BuiltinOperator_AVERAGE_POOL_2D) {
    const auto& d = *static_cast<const tflite::OpDataPooling*>(node->user_data);
    FIELD(d, activation_min); FIELD(d, activation_max);
    Field("padding_height", d.padding.height); Field("padding_width", d.padding.width);
    Field("padding_height_offset", d.padding.height_offset);
    Field("padding_width_offset", d.padding.width_offset);
  } else if (Code == tflite::BuiltinOperator_QUANTIZE) {
    const auto& d = *static_cast<const tflite::OpDataQuantizeReference*>(node->user_data);
    FIELD(d, input_zero_point); Field("output_zero_point", d.quantization_params.zero_point);
    FIELD(d, requantize_output_multiplier); FIELD(d, requantize_output_shift);
  } else if (Code == tflite::BuiltinOperator_SOFTMAX) {
    const auto& d = *static_cast<const tflite::SoftmaxParams*>(node->user_data);
    FIELD(d, input_multiplier); FIELD(d, input_left_shift); FIELD(d, diff_min);
  }
  // Sentinel avoids special casing commas; removed by the reader.
  std::fprintf(output, "\"_end\":0}}");
  ++next_node;
  return std::fflush(output) == 0 ? kTfLiteOk : kTfLiteError;
}
template <int Code>
TFLMRegistration Wrap(TFLMRegistration registration) {
  originals[Code] = registration;
  registration.prepare = Prepare<Code>;
  return registration;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) return 1;
  std::ifstream file(argv[1], std::ios::binary);
  if (!file) return 2;
  const std::vector<char> bytes((std::istreambuf_iterator<char>(file)), {});
  flatbuffers::Verifier verifier(reinterpret_cast<const uint8_t*>(bytes.data()), bytes.size());
  if (!tflite::VerifyModelBuffer(verifier)) return 3;
  model = tflite::GetModel(bytes.data());
  if (model->subgraphs()->size() != 1 || model->version() != TFLITE_SCHEMA_VERSION) return 3;
  output = std::fopen(argv[2], "w");
  if (!output) return 4;
  std::fprintf(output, "[\n");
  tflite::MicroMutableOpResolver<8> resolver;
  if (resolver.AddConv2D(Wrap<tflite::BuiltinOperator_CONV_2D>(tflite::Register_CONV_2D())) != kTfLiteOk ||
      resolver.AddDepthwiseConv2D(Wrap<tflite::BuiltinOperator_DEPTHWISE_CONV_2D>(tflite::Register_DEPTHWISE_CONV_2D())) != kTfLiteOk ||
      resolver.AddFullyConnected(Wrap<tflite::BuiltinOperator_FULLY_CONNECTED>(tflite::Register_FULLY_CONNECTED())) != kTfLiteOk ||
      resolver.AddAdd(Wrap<tflite::BuiltinOperator_ADD>(tflite::Register_ADD())) != kTfLiteOk ||
      resolver.AddAveragePool2D(Wrap<tflite::BuiltinOperator_AVERAGE_POOL_2D>(tflite::Register_AVERAGE_POOL_2D())) != kTfLiteOk ||
      resolver.AddQuantize(Wrap<tflite::BuiltinOperator_QUANTIZE>(tflite::Register_QUANTIZE())) != kTfLiteOk ||
      resolver.AddSoftmax(Wrap<tflite::BuiltinOperator_SOFTMAX>(tflite::Register_SOFTMAX())) != kTfLiteOk ||
      resolver.AddReshape(Wrap<tflite::BuiltinOperator_RESHAPE>(tflite::Register_RESHAPE())) != kTfLiteOk) return 5;
  tflite::MicroInterpreter interpreter(model, resolver, arena, sizeof(arena));
  if (interpreter.AllocateTensors() != kTfLiteOk ||
      next_node != model->subgraphs()->Get(0)->operators()->size()) return 6;
  std::fprintf(output, "\n]\n");
  return std::fclose(output) == 0 ? 0 : 7;
}
