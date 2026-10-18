#pragma once
#include <cstdint>

namespace arch_project::dw {
#if !defined(__riscv)
inline thread_local uint32_t native_lanes[8]{};
#endif
// A session refers to the one architectural hart bank, not a private bank.
// The compiler token orders every hidden-state operation without memory fences.
struct Bank {
#if defined(__riscv) && __riscv_xlen == 64
  uint64_t token=0;
#endif
  template <unsigned Pair> __attribute__((always_inline)) inline void set(uint64_t v){
    static_assert(Pair<4);
#if defined(__riscv) && __riscv_xlen == 64
    asm volatile(".insn r 0x0b, 3, %2, x0, %1, x0" : "+r"(token) : "r"(v),"i"(Pair));
#else
    native_lanes[2*Pair]=uint32_t(v);native_lanes[2*Pair+1]=uint32_t(v>>32);
#endif
  }
  __attribute__((always_inline)) inline void mac(uint64_t a,uint64_t w){
#if defined(__riscv) && __riscv_xlen == 64
    asm volatile(".insn r 0x0b, 2, 0, x0, %1, %2" : "+r"(token) : "r"(a),"r"(w));
#else
    for(unsigned i=0;i<8;++i)native_lanes[i]+=uint32_t(int32_t(int8_t(a>>(8*i)))*int32_t(int8_t(w>>(8*i))));
#endif
  }
  template <unsigned Pair> __attribute__((always_inline)) inline uint64_t get(){
    static_assert(Pair<4);
#if defined(__riscv) && __riscv_xlen == 64
    uint64_t value;
    asm volatile(".insn r 0x0b, 4, %2, %0, x0, x0" : "=&r"(value),"+r"(token) : "i"(Pair));
    return value;
#else
    return uint64_t(native_lanes[2*Pair])|(uint64_t(native_lanes[2*Pair+1])<<32);
#endif
  }
};
inline uint64_t bias_pair(const int32_t* p){uint64_t v;__builtin_memcpy(&v,p,8);return v;}
} // namespace arch_project::dw
