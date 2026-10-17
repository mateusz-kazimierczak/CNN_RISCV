#ifndef ARCH_HOST_DEBUGGER_H
#define ARCH_HOST_DEBUGGER_H
#include "disasm.h"
#include "host_debug_hooks.h"
#include "platform.h"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <limits>
#include <map>
#include <poll.h>
#include <sstream>
#include <sys/socket.h>
#include <unistd.h>

// Private protocol: bounded whitespace commands in, JSON records out. No guest
// code writes, terminal commands, MMIO reads, or per-instruction host round
// trips.
class host_debugger_t {
public:
  host_debug_hooks_t hooks;
  struct breakpoint {
    uint64_t pc;
    int node;
  };
  int fd;
  std::map<uint64_t, breakpoint> breaks;
  std::map<uint64_t, std::string> operators;
  std::vector<std::string> nodes;
  uint64_t invoke = 0, allocate = 0, graph_entry = 0, graph_pointer = 0,
           index_offset = 0, subgraph_offset = 0;
  uint64_t region_return = 0, operator_return = 0;
  int node = -1, entered = -1, target = -1;
  bool inference_done = false, prepared = false, first = true;
  uint64_t running = 0, run_start = 0;
  bool single_step = false, skip_once = false;
  std::string region = "startup", pending_stop, attribution_error, buffer;
  std::chrono::steady_clock::time_point last_progress;

  host_debugger_t(int descriptor, const std::string &config) : fd(descriptor) {
    std::ifstream input(config);
    std::string line;
    if (!input)
      throw std::runtime_error("cannot open debug configuration");
    while (std::getline(input, line)) {
      std::istringstream row(line);
      std::string kind, name;
      uint64_t address;
      row >> kind;
      if (kind == "region") {
        row >> name >> std::hex >> address;
        if (name == "invoke")
          invoke = address;
        else if (name == "allocate")
          allocate = address;
        else
          throw std::runtime_error("bad region");
      } else if (kind == "operator") {
        row >> name >> std::hex >> address;
        operators[address] = name;
      } else if (kind == "node") {
        size_t index;
        row >> index >> name;
        if (index != nodes.size())
          throw std::runtime_error("bad node sequence");
        nodes.push_back(name);
      } else if (kind == "graph")
        row >> std::hex >> graph_entry >> std::dec >> index_offset >>
            subgraph_offset;
      else
        throw std::runtime_error("bad debug configuration record");
      if (!row)
        throw std::runtime_error("invalid debug configuration");
    }
    if (!invoke || !graph_entry || nodes.empty())
      throw std::runtime_error("incomplete debug configuration");
  }
  ~host_debugger_t() { close(fd); }
  static std::string quote(const std::string &s) {
    std::ostringstream o;
    o << '"';
    for (unsigned char c : s) {
      if (c == '"' || c == '\\')
        o << '\\' << char(c);
      else if (c == '\n')
        o << "\\n";
      else if (c == '\r')
        o << "\\r";
      else if (c == '\t')
        o << "\\t";
      else if (c >= 32 && c < 127)
        o << char(c);
      else {
        o << "\\u00" << "0123456789abcdef"[c >> 4]
          << "0123456789abcdef"[c & 15];
      }
    }
    o << '"';
    return o.str();
  }
  void send(const std::string &record) {
    std::string data = record + "\n";
    size_t offset = 0;
    while (offset < data.size()) {
      auto n = ::send(fd, data.data() + offset, data.size() - offset, 0);
      if (n <= 0)
        throw std::runtime_error("debug channel closed");
      offset += n;
    }
  }
  bool line(std::string &out, bool blocking) {
    while (true) {
      auto pos = buffer.find('\n');
      if (pos != std::string::npos) {
        out = buffer.substr(0, pos);
        buffer.erase(0, pos + 1);
        return true;
      }
      pollfd p{fd, POLLIN, 0};
      int result = poll(&p, 1, blocking ? -1 : 0);
      if (result <= 0)
        return false;
      char bytes[4096];
      auto n = recv(fd, bytes, sizeof bytes, 0);
      if (n <= 0)
        throw std::runtime_error("debug channel closed");
      buffer.append(bytes, n);
      if (buffer.size() > 65536)
        throw std::runtime_error("oversized debug command");
    }
  }
  std::vector<uint8_t> memory(sim_t &sim, uint64_t address, size_t size) {
    if (size == 0 || size > 4096 || address > UINT64_MAX - size)
      throw std::runtime_error("memory request must be 1..4096 bytes in RAM");
    for (auto &mem : sim.mems) {
      auto base = mem.first;
      auto length = mem.second->size();
      if (address >= base && address - base < length &&
          size <= length - (address - base)) {
        std::vector<uint8_t> bytes(size);
        if (!mem.second->load(address - base, size, bytes.data()))
          throw std::runtime_error("RAM read failed");
        return bytes;
      }
    }
    throw std::runtime_error(
        "memory read outside configured RAM (MMIO denied)");
  }
  uint32_t scalar(sim_t &sim, uint64_t address) {
    auto bytes = memory(sim, address, 4);
    uint32_t v = 0;
    for (int i = 0; i < 4; i++)
      v |= uint32_t(bytes[i]) << (8 * i);
    return v;
  }
  void prepare(sim_t &sim) {
    if (prepared)
      return;
    prepared = true;
    auto *state = sim.get_core(0)->get_state();
    auto pc = state->pc;
    if (pc == invoke) {
      if (region == "invoke")
        attribution_error = "nested inference unsupported";
      region = "invoke";
      region_return = state->XPR[1];
      entered = -1;
      node = -1;
      inference_done = false;
      pending_stop = "inference-entry";
    } else if (pc == allocate) {
      region = "allocate";
      region_return = state->XPR[1];
    }
    if (pc == graph_entry && region == "invoke")
      graph_pointer = state->XPR[10];
    auto op = operators.find(pc);
    if (op != operators.end() && region == "invoke") {
      if (node != -1)
        attribution_error = "nested operator callback";
      int next = entered + 1;
      try {
        if (!graph_pointer ||
            scalar(sim, graph_pointer + subgraph_offset) != 0 ||
            scalar(sim, graph_pointer + index_offset) != uint32_t(next))
          attribution_error =
              "runtime operator index disagrees with callback sequence";
      } catch (const std::exception &e) {
        attribution_error = e.what();
      }
      if (next >= int(nodes.size()) || nodes[next] != op->second)
        attribution_error = "operator type/order disagrees with model";
      if (attribution_error.empty()) {
        node = entered = next;
        operator_return = state->XPR[1];
      }
    }
  }
  void after(sim_t &sim, uint64_t previous) {
    if (hooks.retired != previous) {
      prepared = false;
      auto pc = sim.get_core(0)->get_state()->pc;
      if (node != -1 && pc == operator_return)
        node = -1;
      if ((region == "invoke" || region == "allocate") && pc == region_return) {
        if (region == "invoke") {
          inference_done = true;
          pending_stop = "inference-complete";
          if (entered + 1 != int(nodes.size()) || node != -1)
            attribution_error =
                "inference ended before expected operators completed";
        }
        region = "outside";
        node = -1;
      }
    }
  }
  std::string snapshot(sim_t &sim, const std::string &reason) {
    auto *core = sim.get_core(0);
    auto *state = core->get_state();
    std::ostringstream o;
    o << "{\"pc\":\"" << state->pc << "\",\"retired\":\"" << hooks.retired
      << "\",\"serializationRetries\":\"" << hooks.retries
      << "\",\"region\":" << quote(region) << ",\"node\":" << node
      << ",\"entered\":" << entered
      << ",\"inferenceComplete\":" << (inference_done ? "true" : "false")
      << ",\"reason\":" << quote(reason) << ",\"registers\":[";
    for (int i = 0; i < 32; i++) {
      if (i)
        o << ',';
      o << '"' << state->XPR[i] << '"';
    }
    o << ']';
    try {
      auto fetch = core->get_mmu()->load_insn(state->pc);
      o << ",\"instruction\":{\"bits\":\"" << fetch.insn.bits()
        << "\",\"length\":" << fetch.insn.length() << ",\"text\":"
        << quote(core->get_disassembler()->disassemble(fetch.insn)) << '}';
    } catch (...) {
      o << ",\"instruction\":null";
    }
    // The pinned Spike reset vector has five 32-bit instructions. The rest
    // is padding, the entry-point pointer and DTB data; never decode that data.
    // Restrict this supplementary window to known ROM code, not MMIO or RAM.
    if (state->pc >= DEFAULT_RSTVEC && state->pc < DEFAULT_RSTVEC + 20 &&
        (state->pc - DEFAULT_RSTVEC) % 4 == 0) {
      o << ",\"instructionWindow\":[";
      bool comma = false;
      for (reg_t pc = DEFAULT_RSTVEC; pc < DEFAULT_RSTVEC + 20; pc += 4) {
        try {
          auto fetch = core->get_mmu()->load_insn(pc);
          if (comma) o << ',';
          comma = true;
          o << "{\"pc\":\"" << pc << "\",\"bits\":\"" << fetch.insn.bits()
            << "\",\"length\":" << fetch.insn.length() << ",\"text\":"
            << quote(core->get_disassembler()->disassemble(fetch.insn)) << '}';
        } catch (...) { break; }
      }
      o << ']';
    }
    if (hooks.trapped)
      o << ",\"trap\":{\"pc\":\"" << hooks.trap_pc << "\",\"cause\":\""
        << hooks.cause << "\",\"name\":" << quote(hooks.trap_name) << '}';
    if (!attribution_error.empty())
      o << ",\"error\":" << quote(attribution_error);
    o << '}';
    return o.str();
  }
  void stopped(sim_t &sim, uint64_t id, const std::string &reason) {
    if (id == running)
      running = 0;
    send("{\"protocol\":1,\"id\":" + std::to_string(id) +
         ",\"type\":\"stopped\",\"snapshot\":" + snapshot(sim, reason) + "}");
  }
  void error(uint64_t id, const std::string &message) {
    send("{\"protocol\":1,\"id\":" + std::to_string(id) +
         ",\"type\":\"error\",\"error\":" + quote(message) + "}");
  }
  // Called from sim_t::idle so HTIF initialization, device ticking and exit
  // handling continue through the normal simulator scheduler.
  void interact(sim_t &sim) {
    if (first) {
      prepare(sim);
      stopped(sim, 0, "ready");
      first = false;
    }
    if (running) {
      if (hooks.waiting) {
        stopped(sim, running, "wait");
        return;
      }
      run_chunk(sim);
      return;
    }
    std::string command;
    if (!line(command, true))
      return;
    uint64_t id = 0;
    std::string op, extra;
    std::istringstream row(command);
    row >> id >> op;
    try {
      if (!row || id == 0)
        throw std::runtime_error("invalid command id");
      if (op == "snapshot") {
        if (row >> extra)
          throw std::runtime_error("extra arguments");
        prepare(sim);
        stopped(sim, id, "snapshot");
      } else if (op == "break") {
        uint64_t key, pc;
        int n;
        row >> key >> pc >> n;
        if (!row || (row >> extra) ||
            (breaks.size() >= 256 && !breaks.count(key)) || n < -1 ||
            n >= int(nodes.size()))
          throw std::runtime_error("invalid breakpoint");
        breaks[key] = {pc, n};
        send("{\"protocol\":1,\"id\":" + std::to_string(id) +
             ",\"type\":\"ok\"}");
      } else if (op == "delete") {
        uint64_t key;
        row >> key;
        if (!row || (row >> extra))
          throw std::runtime_error("invalid breakpoint id");
        breaks.erase(key);
        send("{\"protocol\":1,\"id\":" + std::to_string(id) +
             ",\"type\":\"ok\"}");
      } else if (op == "memory") {
        uint64_t addr;
        size_t size;
        row >> addr >> size;
        if (!row || (row >> extra))
          throw std::runtime_error("invalid memory request");
        auto bytes = memory(sim, addr, size);
        std::string encoded;
        for (auto b : bytes) {
          encoded += "0123456789abcdef"[b >> 4];
          encoded += "0123456789abcdef"[b & 15];
        }
        send("{\"protocol\":1,\"id\":" + std::to_string(id) +
             ",\"type\":\"memory\",\"address\":\"" + std::to_string(addr) +
             "\",\"hex\":" + quote(encoded) + "}");
      } else if (op == "target") {
        row >> target;
        if (!row || (row >> extra) || target < -1 ||
            target >= int(nodes.size()))
          throw std::runtime_error("invalid target");
        send("{\"protocol\":1,\"id\":" + std::to_string(id) +
             ",\"type\":\"ok\"}");
      } else if (op == "run" || op == "step") {
        if (row >> extra)
          throw std::runtime_error("extra arguments");
        running = id;
        single_step = op == "step";
        run_start = hooks.retired;
        skip_once = true;
        hooks.trapped = false;
        hooks.waiting = false;
        pending_stop.clear();
        last_progress = std::chrono::steady_clock::now();
        run_chunk(sim);
      } else if (op == "pause") {
        send("{\"protocol\":1,\"id\":" + std::to_string(id) +
             ",\"type\":\"ok\"}");
      } else if (op == "quit") {
        exit(0);
      } else
        throw std::runtime_error("unknown debug command");
    } catch (const std::exception &e) {
      error(id, e.what());
    }
  }
  void run_chunk(sim_t &sim) {
    auto id = running;
    auto start = run_start;
    bool single = single_step;
    for (int batch = 0; batch < 5000 && !sim.done(); batch++) {
      prepare(sim);
      if (!attribution_error.empty()) {
        stopped(sim, id, "attribution-error");
        return;
      }
      if (!skip_once) {
        if (!pending_stop.empty()) {
          auto reason = pending_stop;
          pending_stop.clear();
          stopped(sim, id, reason);
          return;
        }
        auto pc = sim.get_core(0)->get_state()->pc;
        if (target == node && node >= 0 && operators.count(pc)) {
          target = -1;
          stopped(sim, id, "stage-breakpoint");
          return;
        }
        for (auto &b : breaks)
          if (b.second.pc == pc &&
              (b.second.node < 0 || b.second.node == node)) {
            stopped(sim, id, "breakpoint");
            return;
          }
      }
      skip_once = false;
      auto before = hooks.retired;
      sim.step(1);
      after(sim, before);
      if (hooks.trapped) {
        prepared = false;
        stopped(sim, id, "trap");
        return;
      }
      if (hooks.waiting) {
        // Let HTIF service pending output/exit before declaring a guest wait.
        return;
      }
      if (single && hooks.retired > start) {
        prepare(sim);
        auto reason = pending_stop.empty() ? "step" : pending_stop;
        pending_stop.clear();
        stopped(sim, id, reason);
        return;
      }
      // Poll only in batches, but check breakpoints before every instruction.
      if ((hooks.retired - start) % 4096 == 0) {
        std::string interrupt;
        if (line(interrupt, false)) {
          std::istringstream p(interrupt);
          uint64_t request;
          std::string operation, junk;
          p >> request >> operation;
          if (p && !(p >> junk) && operation == "pause") {
            stopped(sim, id, "pause");
            send("{\"protocol\":1,\"id\":" + std::to_string(request) +
                 ",\"type\":\"ok\"}");
            return;
          }
          error(request, "execution is running; pause first");
        }
        auto now = std::chrono::steady_clock::now();
        if (now - last_progress > std::chrono::milliseconds(250)) {
          last_progress = now;
          send("{\"protocol\":1,\"id\":" + std::to_string(id) +
               ",\"type\":\"progress\",\"retired\":\"" +
               std::to_string(hooks.retired) +
               "\",\"entered\":" + std::to_string(entered) + "}");
        }
      }
    }
    if (sim.done())
      stopped(sim, id, "exited");
  }
};
#endif
