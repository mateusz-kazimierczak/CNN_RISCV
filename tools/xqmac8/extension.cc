// Xqmac8 v1: old rd is a third architectural source. No memory side effects.
#include "extension.h"
#include "insn_macros.h"
#define DECODE_MACRO_USAGE_LOGGED 1
#include "decode_macros.h"
#include <cstdint>

static reg_t execute_qmac8(processor_t* p, insn_t insn, reg_t pc) {
  const auto xlen = p->get_xlen();
  require_rv64;
  const uint64_t a = RS1, w = RS2;
  uint32_t sum = static_cast<uint32_t>(RD);
  for (unsigned i = 0; i < 8; ++i) {
    const unsigned ab = (a >> (8 * i)) & 255, wb = (w >> (8 * i)) & 255;
    const int av = ab < 128 ? int(ab) : int(ab) - 256;
    const int wv = wb < 128 ? int(wb) : int(wb) - 256;
    sum += static_cast<uint32_t>(av * wv);
  }
  const uint64_t result = sum & 0x80000000u ? uint64_t(sum) | 0xffffffff00000000ull : sum;
  // Respect Spike's commit-log switch (and x0), just like standard handlers.
  if (p->get_log_commits_enabled()) STATE.log_reg_write[insn.rd() << 4] = {result, 0};
  STATE.XPR.write(insn.rd(), result);
  return pc + 4;
}

struct register_arg_t : arg_t {
  unsigned which;
  explicit register_arg_t(unsigned n) : which(n) {}
  std::string to_string(insn_t insn) const override {
    return xpr_name[which == 0 ? insn.rd() : which == 1 ? insn.rs1() : insn.rs2()];
  }
};
static register_arg_t destination(0), activation(1), weight(2);

class qmac8_t : public extension_t {
 public:
  const char* name() const override { return "qmac8"; }
  std::vector<insn_desc_t> get_instructions(const processor_t&) override {
    return {{0x0000000b, 0xfe00707f,
      execute_qmac8, execute_qmac8, execute_qmac8, execute_qmac8,
      execute_qmac8, execute_qmac8, execute_qmac8, execute_qmac8}};
  }
  std::vector<disasm_insn_t*> get_disasms(const processor_t*) override {
    return {new disasm_insn_t("xqmac8", 0x0000000b, 0xfe00707f,
                            {&destination, &activation, &weight})};
  }
};
REGISTER_EXTENSION(qmac8, []() { return new qmac8_t; })
