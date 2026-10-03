#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <sys/stat.h>
#include <sys/types.h>

// HTIF packs device=1 (console) and command=1 (write) into the high 16 bits.
// Spike consumes tohost requests and clears the mailbox to acknowledge them.
constexpr std::uint64_t kConsolePutchar = 0x0101000000000000ULL;

extern "C" {
// Keep C symbol names so Spike can discover the mailboxes in the ELF.
volatile std::uint64_t tohost
    __attribute__((section(".tohost"), aligned(8))) = 0;
volatile std::uint64_t fromhost
    __attribute__((section(".fromhost"), aligned(8))) = 0;
extern char __heap_start;
extern char __heap_end;
}

namespace {
char* heap_break = &__heap_start;

}  // namespace

extern "C" void platform_putchar(char character) {
  while (tohost != 0) {
  }
  tohost = kConsolePutchar | static_cast<std::uint8_t>(character);
  while (tohost != 0) {
  }
}

extern "C" [[noreturn]] void platform_exit(int status) {
  while (tohost != 0) {
  }
  tohost = (static_cast<std::uint64_t>(status) << 1) | 1;
  // HTIF reserves odd device-zero requests for process exit.
  while (true) {
    asm volatile("wfi");
  }
}

extern "C" int _write(int, const void* data, std::size_t size) {
  const auto* bytes = static_cast<const char*>(data);
  for (std::size_t index = 0; index < size; ++index) {
    platform_putchar(bytes[index]);
  }
  return static_cast<int>(size);
}

extern "C" void* _sbrk(std::ptrdiff_t increment) {
  // Provide newlib's heap hook within linker-defined bounds. TFLM allocates
  // its tensor buffers from the application arena rather than through _sbrk.
  char* previous = heap_break;
  if (increment < 0 || heap_break + increment > &__heap_end) {
    errno = ENOMEM;
    return reinterpret_cast<void*>(-1);
  }
  heap_break += increment;
  return previous;
}

// Minimal libc hooks for a console-only environment with no filesystem.
extern "C" int _close(int) { return -1; }
extern "C" int _fstat(int, struct stat* status) {
  status->st_mode = S_IFCHR;
  return 0;
}
extern "C" int _isatty(int) { return 1; }
extern "C" int _lseek(int, int, int) { return 0; }
extern "C" int _read(int, void*, std::size_t) { return 0; }
extern "C" int _getpid() { return 1; }
extern "C" int _kill(int, int) {
  errno = EINVAL;
  return -1;
}
extern "C" [[noreturn]] void _exit(int status) { platform_exit(status); }
extern "C" [[noreturn]] void abort() { platform_exit(127); }
extern "C" void __cxa_pure_virtual() { platform_exit(126); }
