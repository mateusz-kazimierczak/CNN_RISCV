// Standalone generated execution: no ML framework headers or libraries.
#include "model.h"
#include "constants.h"
#include "kernels/project/operators.h"
#include "kernels/project/softmax.h"
#include <cstring>
// Generated storage notation:
//   arena.data + N: byte offset in the planned activation workspace.
//   a0_constants.tN: original constant tensor N.
//   a0_constants.pN + K: prepared parameters for node N, offset by K INT32s.
// Node comments list logical graph operands. A kernel may use prepared values
// instead, such as corrected biases in pointwise convolution.
//
// A stable node wrapper supplies the profiler's unit boundary. Its inclusive
// cost includes the kernel and callees; input setup and output checking live
// outside a0_invoke. Shape/scaling labels below are compile-time facts.
#define A0_NOINLINE __attribute__((noinline))
// Compiler barrier: keeps even an alias-only Reshape wrapper observable.
// It emits no target instruction.
#define A0_NODE_ENTRY() asm volatile("" ::: "memory")
