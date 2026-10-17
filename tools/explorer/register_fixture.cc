// Force a stable register allocation to exercise real optimized DWARF locations.
extern "C" int register_fixture(int input) {
  register int accumulator asm("s0") = input;
  for (int i = 0; i < 4; ++i) {
    asm volatile("" : "+r"(accumulator));
    accumulator += i;
  }
  return accumulator;
}
