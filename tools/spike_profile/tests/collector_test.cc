#include "roi_profiler.h"
#include <cassert>
#include <limits>
#include <stdexcept>

int main(int argc, char** argv) {
  assert(argc == 3);
  roi_profiler_t profiler;
  profiler.configure(argv[1], argv[2]);
  // Outside, entry, nested callback, return, tail return of parent.
  profiler.retire(0x80, 1, 2, 0, 0x100, 0);
  profiler.retire(0x100, 1, 2, 0x80, 0x200, 0);
  profiler.retire(0x200, 1, 2, 0x102, 0x202, 0);
  profiler.retire(0x202, 1, 2, 0x102, 0x102, 0);
  profiler.retire(0x102, 1, 2, 0x80, 0x80, 0);
  assert(profiler.events().size() == 2);
  assert(profiler.events()[0].total == 4 && profiler.events()[0].complete);
  assert(profiler.events()[1].total == 2 && profiler.events()[1].complete);
  profiler.write();

  roi_profiler_t::event_t event{};
  event.total = (uint64_t{1} << 32) - 1;
  event.counts = {event.total};
  roi_profiler_t::count(event, 0);
  roi_profiler_t::count(event, 0);
  assert(event.total == (uint64_t{1} << 32) + 1);
  assert(event.counts[0] == event.total);
  event.total = std::numeric_limits<uint64_t>::max();
  bool rejected = false;
  try { roi_profiler_t::count(event, 0); }
  catch (const std::runtime_error&) { rejected = true; }
  assert(rejected);

  roi_profiler_t unfinished;
  unfinished.configure(argv[1], argv[2]);
  unfinished.retire(0x100, 1, 2, 0x80, 0x104, 0);
  assert(!unfinished.events()[0].complete);
  unfinished.trap();
  unfinished.write(); // analyzer must reject this partial capture
}
