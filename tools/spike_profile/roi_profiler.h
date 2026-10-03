// Simulator-side profiling only; no target instructions or runtime changes.
// Included by the pinned Spike patch and also tested independently on the host.
#ifndef ARCH_PROJECT_ROI_PROFILER_H
#define ARCH_PROJECT_ROI_PROFILER_H

#include <cstdint>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

class roi_profiler_t {
 public:
  struct event_t {
    std::string kind, name;
    uint64_t entry, return_pc, total = 0, status = 0;
    bool complete = false;
    std::vector<uint64_t> counts;
  };

  void configure(const std::string& config, const std::string& output) {
    std::ifstream input(config);
    if (!input) throw std::runtime_error("cannot open profile config");
    output_ = output;
    std::string line;
    while (std::getline(input, line)) {
      std::istringstream row(line);
      std::string kind, name, address, end, extra;
      if (!(row >> kind)) continue;
      if (kind == "code") {
        if (!(row >> address >> end) || (row >> extra))
          throw std::runtime_error("invalid code record");
        start_ = std::stoull(address, nullptr, 0);
        end_ = std::stoull(end, nullptr, 0);
      } else {
        if ((kind != "region" && kind != "operator") ||
            !(row >> name >> address) || (row >> extra))
          throw std::runtime_error("invalid profile entry record");
        definitions_.push_back({kind, name, std::stoull(address, nullptr, 0)});
      }
    }
    if (start_ % 2 || end_ <= start_ || end_ - start_ > 16 * 1024 * 1024)
      throw std::runtime_error("invalid profile code range");
    const auto slots = (end_ - start_ + 1) / 2;
    entries_.assign(slots, -1);
    bits_.assign(slots, 0);
    lengths_.assign(slots, 0);
    for (size_t i = 0; i < definitions_.size(); ++i) {
      const auto pc = definitions_[i].pc;
      if (pc < start_ || pc >= end_ || pc % 2 || entries_[(pc - start_) / 2] != -1)
        throw std::runtime_error("invalid or duplicate profile entry address");
      entries_[(pc - start_) / 2] = static_cast<int>(i);
    }
    enabled_ = true;
  }

  bool enabled() const { return enabled_; }

  // Observe entry BEFORE execution, including a first instruction that traps
  // or requests serialization. Retrying that instruction does not re-enter.
  void prepare(uint64_t pc, uint64_t ra) {
    if (!enabled_) return;
    if (pending_ && pc == pending_pc_) return;
    pending_ = true;
    pending_pc_ = pc;
    if (pc < start_ || pc >= end_ || pc % 2) {
      if (region_ != -1) throw std::runtime_error("profile left executable code range");
      return;
    }
    const size_t slot = (pc - start_) / 2;
    const int entry = entries_[slot];
    if (entry != -1) {
      const auto& def = definitions_[entry];
      if (def.kind == "region") {
        if (region_ != -1) throw std::runtime_error("nested profile regions unsupported");
        region_ = begin(def, ra);
      } else if (region_ != -1 && events_[region_].name == "invoke") {
        if (operator_ != -1) throw std::runtime_error("nested operator callbacks unsupported");
        operator_ = begin(def, ra);
      }
    }
  }

  // Called exactly once at retirement, before Spike's timing-after triggers.
  // ra is captured BEFORE execution; npc is not a PC_SERIALIZE sentinel.
  void retire(uint64_t pc, uint64_t bits, unsigned length, uint64_t ra,
              uint64_t npc, uint64_t result) {
    if (!enabled_) return;
    prepare(pc, ra);
    pending_ = false;
    if (region_ == -1) return;
    const size_t slot = (pc - start_) / 2;
    if (length != 2 && length != 4) throw std::runtime_error("unexpected instruction length");
    if (lengths_[slot] && (bits_[slot] != bits || lengths_[slot] != length))
      throw std::runtime_error("self-modifying code unsupported");
    bits_[slot] = bits;
    lengths_[slot] = length;
    count(events_[region_], slot);
    if (operator_ != -1) {
      count(events_[operator_], slot);
      if (npc == events_[operator_].return_pc) {
        finish(events_[operator_], result);
        operator_ = -1;
      }
    }
    if (npc == events_[region_].return_pc) {
      if (operator_ != -1) throw std::runtime_error("region ended inside operator");
      finish(events_[region_], result);
      region_ = -1;
    }
  }

  void trap() {
    if (region_ != -1) faulted_ = true;
  }

  void write() const {
    if (!enabled_) return;
    std::ofstream events(output_ + ".events.csv"), pcs(output_ + ".pcs.csv");
    if (!events || !pcs) throw std::runtime_error("cannot write profile output");
    events << "event_id,kind,name,entry,return_pc,complete,status,total,faulted\n";
    pcs << "event_id,pc,bits,length,count\n";
    for (size_t id = 0; id < events_.size(); ++id) {
      const auto& event = events_[id];
      events << id << ',' << event.kind << ',' << event.name << ',' << event.entry
             << ',' << event.return_pc << ',' << event.complete << ',' << event.status
             << ',' << event.total << ',' << faulted_ << '\n';
      for (size_t slot = 0; slot < event.counts.size(); ++slot) {
        if (!event.counts[slot]) continue;
        pcs << id << ',' << start_ + slot * 2 << ',' << bits_[slot] << ','
            << unsigned(lengths_[slot]) << ',' << event.counts[slot] << '\n';
      }
    }
    if (!events || !pcs) throw std::runtime_error("profile output write failed");
  }

  const std::vector<event_t>& events() const { return events_; }
  // Public for overflow tests and to keep counting semantics in one place.
  static void count(event_t& event, size_t slot) {
    if (event.total == std::numeric_limits<uint64_t>::max() ||
        event.counts[slot] == std::numeric_limits<uint64_t>::max())
      throw std::runtime_error("profile counter overflow");
    ++event.total;
    ++event.counts[slot];
  }

 private:
  struct definition_t { std::string kind, name; uint64_t pc; };
  int begin(const definition_t& def, uint64_t ra) {
    event_t event{};
    event.kind = def.kind;
    event.name = def.name;
    event.entry = def.pc;
    event.return_pc = ra;
    event.counts.assign(entries_.size(), 0);
    events_.push_back(std::move(event));
    return static_cast<int>(events_.size() - 1);
  }
  static void finish(event_t& event, uint64_t result) {
    event.complete = true;
    event.status = result;
  }
  bool enabled_ = false, faulted_ = false, pending_ = false;
  uint64_t pending_pc_ = 0;
  uint64_t start_ = 0, end_ = 0;
  int region_ = -1, operator_ = -1;
  std::string output_;
  std::vector<definition_t> definitions_;
  std::vector<int> entries_;
  std::vector<uint64_t> bits_;
  std::vector<unsigned char> lengths_;
  std::vector<event_t> events_;
};
#endif
