#ifndef ARCH_HOST_DEBUG_HOOKS_H
#define ARCH_HOST_DEBUG_HOOKS_H
#include <cstdint>
#include <string>
struct host_debug_hooks_t {
  uint64_t retired = 0, retries = 0, instruction_pc = 0, last_pc = 0, next_pc = 0;
  bool trapped = false, waiting = false;
  uint64_t trap_pc = 0, cause = 0;
  std::string trap_name;
};
#endif
