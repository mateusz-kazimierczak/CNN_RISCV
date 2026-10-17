// Generated fixed model. A0 is a reference diagnostic configuration, not B1.
#ifndef ARCH_PROJECT_A0_MODEL_H_
#define ARCH_PROJECT_A0_MODEL_H_
#include <cstddef>
#include <cstdint>
#ifndef A0_CAPTURE
#define A0_CAPTURE 0
#endif
extern "C" {
// Input is consumed by Invoke and may share workspace with later tensors.
// Output is exposed only after success, and is valid until the next input setup.
int a0_set_input(const uint8_t* data, std::size_t size);
void a0_fill_input(uint32_t seed);
int a0_invoke();  // 0=success, 2=pinned Softmax domain, 3=state/guard/callback error
int a0_failed_node();
const uint8_t* a0_output();
std::size_t a0_input_bytes();
std::size_t a0_output_bytes();
std::size_t a0_workspace_bytes();
bool a0_guards_ok();
#if A0_CAPTURE
using A0Capture = int (*)(int node, int tensor, const void* data, std::size_t bytes);
void a0_set_capture(A0Capture callback);
uint8_t* a0_debug_guard(int side);
#endif
}
#endif
