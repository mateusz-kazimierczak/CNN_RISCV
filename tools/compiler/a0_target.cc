// Bare-metal generated application. Reuses the existing crt0, linker map and HTIF.
#ifndef COMPILER_CONFIGURATION
#define COMPILER_CONFIGURATION "A0"
#endif
#include "model.h"
#include <cstddef>
#include <cstdint>
extern "C" void platform_putchar(char);
extern "C" char __stack_bottom, __stack_top;
namespace {
void Text(const char* s) { while (*s) platform_putchar(*s++); }
void Decimal(std::size_t value) {
  char digits[24]; int n = 0;
  do { digits[n++] = static_cast<char>('0' + value % 10); value /= 10; } while (value);
  while (n) platform_putchar(digits[--n]);
}
void HexByte(uint8_t value) {
  const char* digits = "0123456789abcdef";
  platform_putchar(digits[value >> 4]); platform_putchar(digits[value & 15]);
}
uintptr_t painted_end;
__attribute__((noinline)) void PaintStack() {
  uintptr_t sp; asm volatile("mv %0, sp" : "=r"(sp));
  // Leave this paint routine's frame and a conservative safety gap untouched.
  painted_end = (sp & ~uintptr_t{15}) - 256;
  for (auto* p = reinterpret_cast<volatile uint32_t*>(&__stack_bottom);
       reinterpret_cast<uintptr_t>(p) < painted_end; ++p) *p = 0xa5c39e71u;
}
std::size_t StackWatermark() {
  uintptr_t first = painted_end;
  for (auto* p = reinterpret_cast<volatile uint32_t*>(&__stack_bottom);
       reinterpret_cast<uintptr_t>(p) < painted_end; ++p) {
    if (*p != 0xa5c39e71u) { first = reinterpret_cast<uintptr_t>(p); break; }
  }
  return reinterpret_cast<uintptr_t>(&__stack_top) - first;
}
}

int main() {
  a0_fill_input(1);
  PaintStack();
  const int status = a0_invoke();
  const auto stack_watermark = StackWatermark();
  const bool guards = a0_guards_ok();
  if (status || !guards || !a0_output()) { Text(COMPILER_CONFIGURATION " inference: FAIL\n"); return 1; }
  const uint8_t* output = a0_output();
  uint32_t hash = 2166136261u;
  std::size_t sum = 0, top = 0;
  for (std::size_t i = 0; i < a0_output_bytes(); ++i) {
    hash = (hash ^ output[i]) * 16777619u;
    sum += output[i]; if (output[i] > output[top]) top = i;
  }
  Text(COMPILER_CONFIGURATION " EfficientNet-Lite0 inference: PASS\nworkspace_bytes="); Decimal(a0_workspace_bytes());
  Text("\noutput_top_index="); Decimal(top); Text(" output_top_score="); Decimal(output[top]);
  Text(" output_sum="); Decimal(sum); Text("\noutput_fnv1a=0x");
  for (int shift = 24; shift >= 0; shift -= 8) HexByte(static_cast<uint8_t>(hash >> shift));
  Text("\nstack_watermark_bytes="); Decimal(stack_watermark);
  Text("\noutput_hex=");
  for (std::size_t i = 0; i < a0_output_bytes(); ++i) HexByte(output[i]);
  Text("\n");
  return 0;
}
