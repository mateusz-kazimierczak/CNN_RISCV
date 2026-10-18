// Separate plugin preserves the pinned Xqmac8 extension and simulator binaries.
#include "extension.h"
#include "insn_macros.h"
#define DECODE_MACRO_USAGE_LOGGED 1
#include "decode_macros.h"
#include "kernels/xrequant/requant.h"
static reg_t execute_requant(processor_t* p, insn_t insn, reg_t pc) {
  const auto xlen = p->get_xlen();
  require_rv64;
  const uint64_t a = RS1, d = RS2; // Snapshot before writeback, including aliases.
  const uint32_t m = uint32_t(d);
  const unsigned r = (d >> 32) & 63;
  const int z = int8_t(d >> 38), lo = int8_t(d >> 46), hi = int8_t(d >> 54);
  const bool scale = (d >> 62) & 1;
  require(!(d >> 63) && m <= 0x7fffffffu && r <= 31 && lo <= hi &&
          (!scale || (!z && !lo && !hi)));
  const uint64_t result = uint64_t(arch_project::xrequant(int64_t(a), d));
  if (p->get_log_commits_enabled()) STATE.log_reg_write[insn.rd() << 4] = {result, 0};
  STATE.XPR.write(insn.rd(), result);
  return pc + 4;
}
struct argument_t : arg_t {
  unsigned which;
  explicit argument_t(unsigned n) : which(n) {}
  std::string to_string(insn_t i) const override { return xpr_name[which == 0 ? i.rd() : which == 1 ? i.rs1() : i.rs2()]; }
};
static argument_t rd(0), rs1(1), rs2(2);
class requant_t : public extension_t {
 public:
  const char* name() const override { return "requant"; }
  std::vector<insn_desc_t> get_instructions(const processor_t&) override {
    return {{0x0000100b, 0xfe00707f,
      execute_requant,execute_requant,execute_requant,execute_requant,
      execute_requant,execute_requant,execute_requant,execute_requant}};
  }
  std::vector<disasm_insn_t*> get_disasms(const processor_t*) override {
    return {new disasm_insn_t("xrequant",0x0000100b,0xfe00707f,{&rd,&rs1,&rs2})};
  }
};
REGISTER_EXTENSION(requant, [](){ return new requant_t; })
