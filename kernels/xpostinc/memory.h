// Alias-safe memory operands with two explicit load outputs. No global barrier.
#pragma once
#include <cstdint>
#include <type_traits>

namespace arch_project::postinc {
template <unsigned Bytes> struct Memory { unsigned char data[Bytes]; };
template <class T, int Increment>
inline T load(const int8_t*& pointer) {
  static_assert(std::is_integral_v<T> && sizeof(T) <= 8);
  static_assert(Increment >= -2048 && Increment <= 2047);
#if defined(__riscv) && __riscv_xlen == 64
  constexpr unsigned width = sizeof(T) == 8 ? 3 : sizeof(T) == 4 ? 2 : sizeof(T) == 2 ? 1 : 0;
  constexpr unsigned function = width + (std::is_unsigned_v<T> && sizeof(T) != 8 ? 4 : 0);
  uint64_t result;
  asm volatile(".insn i 0x2b, %3, %0, %1, %2"
               : "=&r"(result), "+r"(pointer)
               : "i"(Increment), "i"(function),
                 "m"(*reinterpret_cast<const Memory<sizeof(T)>*>(pointer)));
  return static_cast<T>(result);
#else
  if (reinterpret_cast<uintptr_t>(pointer) % alignof(T)) __builtin_trap();
  T result;
  __builtin_memcpy(&result, pointer, sizeof(T));
  pointer = reinterpret_cast<const int8_t*>(reinterpret_cast<uintptr_t>(pointer) + static_cast<uintptr_t>(Increment));
  return result;
#endif
}
template <class T, int Increment>
inline void store(int8_t*& pointer, T value) {
  static_assert(std::is_integral_v<T> && sizeof(T) <= 8);
  static_assert(Increment >= -2048 && Increment <= 2047);
#if defined(__riscv) && __riscv_xlen == 64
  constexpr unsigned function = sizeof(T) == 8 ? 3 : sizeof(T) == 4 ? 2 : sizeof(T) == 2 ? 1 : 0;
  asm volatile(".insn i 0x7b, %3, %2, %0, %4"
               : "+r"(pointer), "=m"(*reinterpret_cast<Memory<sizeof(T)>*>(pointer))
               : "r"(value), "i"(function), "i"(Increment));
#else
  if (reinterpret_cast<uintptr_t>(pointer) % alignof(T)) __builtin_trap();
  __builtin_memcpy(pointer, &value, sizeof(T));
  pointer = reinterpret_cast<int8_t*>(reinterpret_cast<uintptr_t>(pointer) + static_cast<uintptr_t>(Increment));
#endif
}
}  // namespace arch_project::postinc
