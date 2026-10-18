#include "extension.h"
#include "insn_macros.h"
#define DECODE_MACRO_USAGE_LOGGED 1
#include "decode_macros.h"
#include <array>

static reg_t execute_bank(processor_t*, insn_t, reg_t);
struct argument_t : arg_t {
  unsigned which;
  explicit argument_t(unsigned n):which(n){}
  std::string to_string(insn_t i) const override {
    return xpr_name[which==0?i.rd():which==1?i.rs1():i.rs2()];
  }
};
static argument_t rd(0), rs1(1), rs2(2);
class dwmac8_t : public extension_t {
 public:
  std::array<uint32_t,8> lanes{};
  const char* name() const override {return "dwmac8";}
  void reset(processor_t&) override {lanes.fill(0);}
  std::vector<insn_desc_t> get_instructions(const processor_t&) override {
    std::vector<insn_desc_t> result;
    auto add=[&](uint32_t match,uint32_t mask){result.push_back({match,mask,
      execute_bank,execute_bank,execute_bank,execute_bank,
      execute_bank,execute_bank,execute_bank,execute_bank});};
    add(0x200b,0xfe007fff);
    for(unsigned i=0;i<4;++i){add(0x300b|(i<<25),0xfff07fff);add(0x400b|(i<<25),0xfffff07f);}
    return result;
  }
  std::vector<disasm_insn_t*> get_disasms(const processor_t*) override {
    std::vector<disasm_insn_t*> result{new disasm_insn_t("xdwmac8",0x200b,0xfe007fff,{&rs1,&rs2})};
    for(unsigned i=0;i<4;++i){
      result.push_back(new disasm_insn_t(("xdwset"+std::to_string(i)).c_str(),0x300b|(i<<25),0xfff07fff,{&rs1}));
      result.push_back(new disasm_insn_t(("xdwget"+std::to_string(i)).c_str(),0x400b|(i<<25),0xfffff07f,{&rd}));
    }
    return result;
  }
};
static reg_t execute_bank(processor_t* p,insn_t insn,reg_t pc){
  const auto xlen=p->get_xlen();require_rv64;
  auto& bank=static_cast<dwmac8_t*>(p->get_extension("dwmac8"))->lanes;
  const uint64_t a=RS1,w=RS2;
  const unsigned pair=insn.funct7();
  if(insn.funct3()==2){
    auto next=bank;
    for(unsigned i=0;i<8;++i){
      const int x=int8_t(a>>(8*i)),y=int8_t(w>>(8*i));
      next[i]+=uint32_t(x*y);
    }
    bank=next;
  }else if(insn.funct3()==3){bank[2*pair]=uint32_t(a);bank[2*pair+1]=uint32_t(a>>32);
  }else{
    const reg_t value=uint64_t(bank[2*pair])|(uint64_t(bank[2*pair+1])<<32);
    if(insn.rd()){
      if(p->get_log_commits_enabled())STATE.log_reg_write[insn.rd()<<4]={value,0};
      STATE.XPR.write(insn.rd(),value);
    }
  }
  return pc+4;
}
REGISTER_EXTENSION(dwmac8, [](){return new dwmac8_t;})
