#include "tensorflow/lite/micro/debug_log.h"

#include <cstdarg>
#include <cstddef>
#include <cstdio>

extern "C" void platform_putchar(char character);

extern "C" void DebugLog(const char* format, va_list arguments) {
  // Bound each log message on the stack; long messages are truncated before
  // sending characters synchronously through Spike's HTIF console.
  char buffer[256];
  const int count = vsnprintf(buffer, sizeof(buffer), format, arguments);
  if (count <= 0) {
    return;
  }
  const std::size_t bounded_count =
      static_cast<std::size_t>(count) < sizeof(buffer)
          ? static_cast<std::size_t>(count)
          : sizeof(buffer) - 1;
  for (std::size_t index = 0; index < bounded_count; ++index) {
    platform_putchar(buffer[index]);
  }
}

extern "C" int DebugVsnprintf(char* buffer, std::size_t size,
                               const char* format, va_list arguments) {
  return vsnprintf(buffer, size, format, arguments);
}
