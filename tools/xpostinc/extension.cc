// Xpostinc: memory accesses precede either register write, preserving traps.
#include "extension.h"
#include "insn_macros.h"
#define DECODE_MACRO_USAGE_LOGGED 1
#include "decode_macros.h"
#include "mmu.h"

static void write_register(processor_t* p, unsigned reg, reg_t value) {
  if (!reg) return;
  if (p->get_log_commits_enabled()) STATE.log_reg_write[reg << 4] = {value, 0};
  STATE.XPR.write(reg, value);
}
static reg_t execute_postinc(processor_t* p, insn_t insn, reg_t pc) {
  const auto xlen = p->get_xlen();
  require_rv64;
  const unsigned f = insn.funct3();
  const bool store = (insn.bits() & 127) == 0x7b;
  require(store ? f < 4 : f < 7);
  require(store || insn.rd() == 0 || insn.rd() != insn.rs1());
  const reg_t address = RS1;
  const reg_t source = STATE.XPR[insn.rd()];
  const reg_t next = address + insn.i_imm();
  const unsigned bytes = 1u << (f & 3);
  if (address & (bytes - 1)) {
    if (store) throw trap_store_address_misaligned(STATE.v, address, 0, 0);
    throw trap_load_address_misaligned(STATE.v, address, 0, 0);
  }
  if (store) {
    switch (f) {
      case 0: MMU.store<uint8_t>(address, source); break;
      case 1: MMU.store<uint16_t>(address, source); break;
      case 2: MMU.store<uint32_t>(address, source); break;
      case 3: MMU.store<uint64_t>(address, source); break;
    }
  } else {
    reg_t value = 0;
    switch (f) {
      case 0: value = MMU.load<int8_t>(address); break;
      case 1: value = MMU.load<int16_t>(address); break;
      case 2: value = MMU.load<int32_t>(address); break;
      case 3: value = MMU.load<uint64_t>(address); break;
      case 4: value = MMU.load<uint8_t>(address); break;
      case 5: value = MMU.load<uint16_t>(address); break;
      case 6: value = MMU.load<uint32_t>(address); break;
    }
    write_register(p, insn.rd(), value);
  }
  write_register(p, insn.rs1(), next);
  return pc + 4;
}
struct argument_t : arg_t {
  unsigned which;
  explicit argument_t(unsigned n) : which(n) {}
  std::string to_string(insn_t i) const override {
    return which == 2 ? std::to_string(i.i_imm()) : xpr_name[which == 0 ? i.rd() : i.rs1()];
  }
};
static argument_t value(0), base(1), increment(2);
class postinc_t : public extension_t {
 public:
  const char* name() const override { return "postinc"; }
  std::vector<insn_desc_t> get_instructions(const processor_t&) override {
    std::vector<insn_desc_t> result;
    for (unsigned op : {0x2bu, 0x7bu})
      for (unsigned f = 0; f < (op == 0x2b ? 7u : 4u); ++f)
        result.push_back({op | (f << 12), 0x707f,
          execute_postinc, execute_postinc, execute_postinc, execute_postinc,
          execute_postinc, execute_postinc, execute_postinc, execute_postinc});
    return result;
  }
  std::vector<disasm_insn_t*> get_disasms(const processor_t*) override {
    const char* loads[] = {"xlbpi", "xlhpi", "xlwpi", "xldpi", "xlbupi", "xlhupi", "xlwupi"};
    const char* stores[] = {"xsbpi", "xshpi", "xswpi", "xsdpi"};
    std::vector<disasm_insn_t*> result;
    for (unsigned op : {0x2bu, 0x7bu})
      for (unsigned f = 0; f < (op == 0x2b ? 7u : 4u); ++f)
        result.push_back(new disasm_insn_t(op == 0x2b ? loads[f] : stores[f],
          op | (f << 12), 0x707f, {&value, &base, &increment}));
    return result;
  }
};
REGISTER_EXTENSION(postinc, [](){ return new postinc_t; })
