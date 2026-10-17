// Host-only capture/guard harness. File I/O and verification are outside Invoke.
#include "model.h"
#include <cstdio>
#include <cstring>
#include <vector>

namespace {
const char* directory;
std::FILE* table;
int captured = 0;
bool Write(const char* name, const void* data, std::size_t bytes) {
  char path[4096];
  if (std::snprintf(path, sizeof(path), "%s/%s", directory, name) >= static_cast<int>(sizeof(path))) return false;
  auto* file = std::fopen(path, "wb");
  if (!file) return false;
  bool ok = std::fwrite(data, 1, bytes, file) == bytes;
  return std::fclose(file) == 0 && ok;
}
#if A0_CAPTURE
int Capture(int node, int tensor, const void* data, std::size_t bytes) {
  if (node != captured) return 1;
  char name[96];
  std::snprintf(name, sizeof(name), "node_%02d_output_0_tensor_%03d.bin", node, tensor);
  if (!Write(name, data, bytes)) return 1;
  std::fprintf(table, "%d\t%d\t%zu\t%s\n", node, tensor, bytes, name);
  ++captured;
  return std::fflush(table) == 0 ? 0 : 1;
}
#endif
}  // namespace

int main(int argc, char** argv) {
  if (argc < 3 || argc > 4) return 10;
  uint8_t byte = 0;
  if (a0_invoke() != 3 || a0_output() != nullptr ||
      a0_set_input(nullptr, a0_input_bytes()) != 3 || a0_set_input(&byte, 0) != 3) return 17;
  if (argc == 4 && std::strcmp(argv[3], "--corrupt-guard") != 0 && std::strcmp(argv[3], "--recover") != 0) return 10;
  directory = argv[2];
  if (std::strcmp(argv[1], "-") == 0) {
    a0_fill_input(1);
  } else {
    auto* file = std::fopen(argv[1], "rb");
    if (!file) return 11;
    std::vector<uint8_t> input(a0_input_bytes());
    bool ok = std::fread(input.data(), 1, input.size(), file) == input.size();
    ok = ok && std::fgetc(file) == EOF && !std::ferror(file);
    ok = std::fclose(file) == 0 && ok;
    if (!ok || a0_set_input(input.data(), input.size())) return 11;
  }
  char path[4096];
  std::snprintf(path, sizeof(path), "%s/tensors.tsv", directory);
  table = std::fopen(path, "w");
  if (!table) return 12;
  std::fprintf(table, "node\ttensor\tbytes\tfile\n");
#if A0_CAPTURE
  a0_set_capture(Capture);
  if (argc == 4 && std::strcmp(argv[3], "--corrupt-guard") == 0) *a0_debug_guard(0) ^= 1;
#else
  if (argc == 4) return 13;
#endif
  int status = a0_invoke();
  const int failed_node = a0_failed_node();
  bool guards = a0_guards_ok();
  bool ok = std::fclose(table) == 0;
  auto* output = a0_output();
  if (status == 0) ok = output && Write("output.bin", output, a0_output_bytes()) && ok;
  else ok = output == nullptr && ok;
  char result[256];
  const int size = std::snprintf(result, sizeof(result), "{\"status\":%d,\"failed_node\":%d,\"captured_nodes\":%d,\"guards\":%s,\"output_available\":%s}\n",
      status, failed_node, captured, guards ? "true" : "false", output ? "true" : "false");
  ok = Write("result.json", result, static_cast<std::size_t>(size)) && ok;
  if (!ok) return 14;
  // A second invocation without new input must reject consumed input storage.
  if (a0_invoke() != 3) return 15;
  if (a0_output() != nullptr) return 15;
  if (argc == 4 && std::strcmp(argv[3], "--recover") == 0) {
#if A0_CAPTURE
    a0_set_capture(nullptr);
#endif
    a0_fill_input(1);
    if (a0_invoke() != 0 || !a0_guards_ok() || !a0_output() ||
        !Write("recovered-output.bin", a0_output(), a0_output_bytes())) return 16;
  }
  std::printf("A0 status=%d failed_node=%d captured_nodes=%d guards=%s\n", status, failed_node, captured, guards ? "PASS" : "FAIL");
  return status;
}
