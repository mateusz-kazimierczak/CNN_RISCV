// Investigation harness only. Restoration and byte checks are outside replay_invoke.
#include <cstddef>
#include <cstdint>
#include <cstring>
#if REPLAY_NATIVE
#include <cstdio>
#endif
#include "model.h"
#include "replay_fixtures.h"
extern "C" {
extern const uint8_t replay_fixture_begin[];
void replay_reset();
uint8_t* replay_arena();
void replay_corrupt_guard();
#if !REPLAY_NATIVE
void platform_putchar(char);
#endif
}
namespace {
const Fixture* active;
int32_t dot_result;
void Text(const char* text) {
  while (*text) {
#if REPLAY_NATIVE
    std::putchar(*text++);
#else
    platform_putchar(*text++);
#endif
  }
}
void Number(std::size_t n) {
  char digits[24]; unsigned count = 0;
  do { digits[count++] = static_cast<char>('0' + n % 10); n /= 10; } while (n);
  while (count) { char one[] = {digits[--count], 0}; Text(one); }
}
}
extern "C" __attribute__((noinline)) int replay_dot() {
  return cc_dot(reinterpret_cast<const int8_t*>(replay_fixture_begin + active->inputs[0].pack),
                reinterpret_cast<const int8_t*>(replay_fixture_begin + active->inputs[1].pack),
                active->count, active->offset, active->bias, &dot_result);
}
extern "C" __attribute__((noinline)) int replay_invoke(int (*entry)()) {
  return entry();
}
#if REPLAY_NATIVE
int main(int argc, char** argv) {
  const bool corrupt = argc == 2 && std::strcmp(argv[1], "--corrupt-output") == 0;
  const bool corrupt_guard = argc == 2 && std::strcmp(argv[1], "--corrupt-guard") == 0;
  if (argc > 1 && !corrupt && !corrupt_guard) return 4;
#else
int main() {
  constexpr bool corrupt = false, corrupt_guard = false;
#endif
  unsigned index = 0;
  for (const auto& fixture : fixtures) {
    replay_reset();
    active = &fixture;
    uint8_t* output = fixture.count ? reinterpret_cast<uint8_t*>(&dot_result)
                                    : replay_arena() + fixture.output.arena;
    const uint8_t* expected = replay_fixture_begin + fixture.output.pack;
    if (!fixture.aliases)
      for (std::size_t i = 0; i < fixture.output.size; ++i)
        output[i] = fixture.status ? expected[i] : static_cast<uint8_t>(expected[i] ^ 0xff);
    if (!fixture.count)
      for (unsigned i = 0; i < fixture.input_count; ++i)
        std::memcpy(replay_arena() + fixture.inputs[i].arena,
                    replay_fixture_begin + fixture.inputs[i].pack, fixture.inputs[i].size);
    if (corrupt_guard) replay_corrupt_guard();
    if (!a0_guards_ok()) { Text("replay guard failure before invoke\n"); return 3; }
    const int status = replay_invoke(fixture.entry);
    if (corrupt) output[0] ^= 0xff;
    std::size_t first = fixture.output.size;
    for (std::size_t i = 0; i < fixture.output.size; ++i)
      if (output[i] != expected[i] && first == fixture.output.size) first = i;
    const bool guards = a0_guards_ok();
    Text("{\"fixture\":"); Number(index++);
    Text(",\"status\":"); Number(static_cast<unsigned>(status));
    Text(",\"guards\":"); Text(guards ? "true" : "false");
    Text(",\"bytes_compared\":"); Number(fixture.output.size);
    Text(",\"first_difference\":");
    if (first == fixture.output.size) Text("null"); else Number(first);
    Text("}\n");
    if (status != fixture.status || !guards || first != fixture.output.size) return 1;
  }
  Text("compiler replay: PASS\n");
  return 0;
}
