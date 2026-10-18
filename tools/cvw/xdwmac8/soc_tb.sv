// SPDX-License-Identifier: Apache-2.0
// Real CV-Wally SoC, its caches, privilege/trap machinery and AHB RAM.
// Architectural test programs check their own results; the host observes exit.
`include "config.vh"
import cvw::*;
module xdwmac8_soc_tb;
  `include "parameter-defs.vh"
  logic clk = 0, reset_ext = 1, reset;
  logic ExternalStall;
  logic [P.AHBW-1:0] HRDATAEXT = '0;
  logic HREADYEXT = 1, HRESPEXT = 0, HSELEXT;
  logic HCLK, HRESETn, HWRITE, HMASTLOCK, HREADY;
  logic [P.PA_BITS-1:0] HADDR;
  logic [P.AHBW-1:0] HWDATA;
  logic [P.XLEN/8-1:0] HWSTRB;
  logic [2:0] HSIZE, HBURST;
  logic [3:0] HPROT;
  logic [1:0] HTRANS;
  logic [31:0] GPIOOUT, GPIOEN;
  logic UARTSout, SPIOut, SPICLK, SDCCmd, SDCCLK;
  logic [3:0] SPICS, SDCCS, PWMGPIO;
  string image;
  longint unsigned cycles = 0, retired = 0, custom = 0, traps = 0;
  longint unsigned tohost = 0, maxcycles = 100000000, expected_custom = 0, expected_traps = 0;
  longint unsigned forward_m = 0, forward_w = 0, oldrd_load_stalls = 0;
  longint unsigned oldrd_mdu_stalls = 0, oldrd_csr_stalls = 0;
  longint unsigned flushes = 0;
  longint unsigned qmac = 0, requant = 0, expected_qmac = 0, expected_requant = 0;
  longint unsigned req_forward_m = 0, req_forward_w = 0, req_load = 0, req_mdu = 0, req_csr = 0;
  longint unsigned descriptor_faults = 0;
  longint unsigned postload = 0, poststore = 0, expected_postload = 0, expected_poststore = 0;
  longint unsigned base_forward_m = 0, base_forward_w = 0, base_writes = 0;
  longint unsigned base_a_m = 0, base_b_m = 0, base_c_m = 0;
  longint unsigned base_a_w = 0, base_b_w = 0, base_c_w = 0;
  longint unsigned post_faults = 0;
  logic post_fault_pending;
  longint unsigned dwmac = 0, dwset[4] = '{default:0}, dwget[4] = '{default:0};
  longint unsigned expected_dwmac = 0, expected_dwset[4] = '{default:0}, expected_dwget[4] = '{default:0};
  longint unsigned bank_forward = 0, bank_stall = 0, bank_flush = 0, bank_trap = 0;
  longint unsigned dw_forward_m = 0, dw_forward_w = 0, dw_load = 0, dw_mdu = 0, dw_csr = 0;
  longint unsigned irq_pc = 0;
  logic irq_fired = 0;
  integer stall_period = 0;
  logic host_read_w = 0;
  wire commit = dut.core.InstrValidM && !dut.core.StallW && !dut.core.FlushW;
  wire [63:0] store_value = {{(64-P.XLEN){1'b0}}, dut.core.ieu.dp.WriteDataM};

  wallypipelinedsoc #(P) dut(
    .clk, .reset_ext, .reset, .ExternalStall,
    .HRDATAEXT, .HREADYEXT, .HRESPEXT, .HSELEXT,
    .HCLK, .HRESETn, .HADDR, .HWDATA, .HWSTRB, .HWRITE, .HSIZE,
    .HBURST, .HPROT, .HTRANS, .HMASTLOCK, .HREADY,
    .TIMECLK(clk), .GPIOIN(32'b0), .GPIOOUT, .GPIOEN,
    .UARTSin(1'b1), .UARTSout, .SPIIn(1'b0), .SPIOut, .SPICS, .SPICLK,
    .SDCIn(1'b0), .SDCCmd, .SDCCS, .SDCCLK, .PWMGPIO
  );
  always #5 clk = !clk;
  assign ExternalStall = stall_period > 0 && !reset &&
                         (cycles % 64'(stall_period) >= 64'(stall_period)-3);
  initial begin
    if (!$value$plusargs("IMAGE=%s", image)) $fatal(1, "missing image");
    if (!$value$plusargs("TOHOST=%h", tohost)) $fatal(1, "missing tohost");
    if (!$value$plusargs("EXPECTED_CUSTOM=%d", expected_custom)) expected_custom = 0;
    if (!$value$plusargs("EXPECTED_TRAPS=%d", expected_traps)) expected_traps = 0;
    if (!$value$plusargs("MAX_CYCLES=%d", maxcycles)) maxcycles = 100000000;
    if (!$value$plusargs("STALL_PERIOD=%d", stall_period)) stall_period = 0;
    if (!$value$plusargs("EXPECTED_QMAC=%d", expected_qmac)) expected_qmac = 0;
    if (!$value$plusargs("EXPECTED_REQUANT=%d", expected_requant)) expected_requant = 0;
    if (!$value$plusargs("EXPECTED_POSTLOAD=%d", expected_postload)) expected_postload = 0;
    if (!$value$plusargs("EXPECTED_POSTSTORE=%d", expected_poststore)) expected_poststore = 0;
    if (!$value$plusargs("EXPECTED_DWMAC=%d", expected_dwmac)) expected_dwmac = 0;
    if (!$value$plusargs("IRQ_PC=%h", irq_pc)) irq_pc = 0;
    for (int i=0;i<4;i++) begin
      if (!$value$plusargs($sformatf("EXPECTED_DWSET%0d=%%d",i), expected_dwset[i])) expected_dwset[i] = 0;
      if (!$value$plusargs($sformatf("EXPECTED_DWGET%0d=%%d",i), expected_dwget[i])) expected_dwget[i] = 0;
    end
    $readmemh(image, dut.uncoregen.uncore.ram.ram.memory.ram.RAM);
    repeat (8) @(negedge clk);
    reset_ext = 0;
  end
  // A test interrupt changes only an interrupt source, never an operand/result.
  // Trigger halfway through the target M-stage instruction, before acceptance.
  always @(negedge clk) begin
    if (irq_pc != 0) begin
      if (!reset && !irq_fired && dut.core.PCM == P.XLEN'(irq_pc))
        force dut.core.MTimerInt = 1'b1;
      else force dut.core.MTimerInt = 1'b0;
    end else release dut.core.MTimerInt;
  end
  always @(posedge clk)
    if (!reset && irq_pc != 0 && dut.core.PCM == P.XLEN'(irq_pc) && dut.core.TrapM && !dut.core.StallW)
      irq_fired <= 1;

  if (P.XDWMAC8_SUPPORTED && P.XLEN == 64) begin : bank_assertions
    logic [255:0] expected_bank;
    always @(posedge clk) begin
      expected_bank = reset ? '0 : dut.core.ieu.dp.xdwmac8gen.bank.Bank;
      if (!reset) begin
        if (dut.core.ieu.dp.xdwmac8gen.bank.WriteM && !dut.core.StallM && !dut.core.FlushW)
          expected_bank = dut.core.ieu.dp.xdwmac8gen.bank.NextM;
        if (dut.core.ieu.XdwMacE || dut.core.ieu.XdwSetE || dut.core.ieu.XdwGetE) begin
          if (dut.core.StallE) bank_stall++;
          if (dut.core.FlushM) bank_flush++;
          if (!dut.core.StallE && dut.core.ieu.dp.xdwmac8gen.bank.WriteM) bank_forward++;
          if (!dut.core.StallE && (dut.core.ieu.c.ForwardAE == 2 || dut.core.ieu.c.ForwardBE == 2)) dw_forward_m++;
          if (!dut.core.StallE && (dut.core.ieu.c.ForwardAE == 1 || dut.core.ieu.c.ForwardBE == 1)) dw_forward_w++;
        end
        if (dut.core.ieu.dp.xdwmac8gen.bank.WriteM && dut.core.FlushW && !dut.core.StallW) bank_trap++;
        if (dut.core.ieu.c.XdwMacD || dut.core.ieu.c.XdwSetD) begin
          if (dut.core.ieu.c.LoadStallD) dw_load++;
          if (dut.core.ieu.c.MDUStallD) dw_mdu++;
          if (dut.core.ieu.c.CSRRdStallD) dw_csr++;
        end
      end
      #1;
      if (dut.core.ieu.dp.xdwmac8gen.bank.Bank !== expected_bank)
        $fatal(1,"bank changed outside precise retirement or reset");
    end
  end
  // Same explicit HTIF console acknowledgement as the baseline monitor. Only
  // mailbox loads are acknowledged; no register/operand/result is supplied by
  // the oracle. This also supports unmodified compiler kernel replay drivers.
  always @(posedge clk) begin
    if (reset) host_read_w <= 0;
    else if (!dut.core.StallW)
      host_read_w <= commit && dut.core.lsu.IEUAdrM == P.XLEN'(tohost) && dut.core.lsu.MemRWM[1];
    #1;
    if (host_read_w) force dut.core.ReadDataW = '0;
    else release dut.core.ReadDataW;
  end
  // Assert the two-result contract at retirement and trap boundaries.
  always @(posedge clk) begin
    post_fault_pending = !reset && dut.core.TrapM && dut.core.XpostincM;
    if (post_fault_pending) post_faults++;
    if (!reset && commit && dut.core.XpostincM) begin
      if (dut.core.ieu.dp.BaseResultM != dut.core.lsu.IEUAdrM + P.XLEN'($signed(dut.core.InstrM[31:20])))
        $fatal(1, "base increment does not use old access address");
      if (dut.core.ieu.c.BaseRdM != dut.core.InstrM[19:15]) $fatal(1, "wrong base destination");
    end
    #1;
    if (post_fault_pending && dut.core.ieu.c.XpostincW) $fatal(1, "faulting postincrement reached writeback");
  end
  always @(negedge clk) begin
    if (!reset && dut.core.ieu.RegWriteW && dut.core.ieu.c.RegWriteBaseW &&
        dut.core.ieu.c.RdW != 0 && dut.core.ieu.c.RdW == dut.core.ieu.c.BaseRdW)
      $fatal(1, "two register results target the same nonzero register");
  end
  always @(posedge clk) begin
    if (!reset) begin
      cycles = cycles + 1;
      if (cycles >= maxcycles) $fatal(1, "cycle limit");
      if (dut.core.TrapM && !dut.core.StallW) traps = traps + 1;
      if (dut.core.FlushE && !dut.core.StallE) flushes = flushes + 1;
      if (dut.core.ieu.c.Xqmac8E && !dut.core.StallE) begin
        if (dut.core.ieu.c.ForwardCE == 2) forward_m = forward_m + 1;
        if (dut.core.ieu.c.ForwardCE == 1) forward_w = forward_w + 1;
      end
      if (dut.core.ieu.c.Xqmac8D && dut.core.ieu.c.RdD == dut.core.ieu.c.RdE &&
          dut.core.ieu.c.RdE != 0 && dut.core.ieu.c.Rs1D != dut.core.ieu.c.RdE &&
          dut.core.ieu.c.Rs2D != dut.core.ieu.c.RdE) begin
        if (dut.core.ieu.c.LoadStallD) oldrd_load_stalls = oldrd_load_stalls + 1;
        if (dut.core.ieu.c.MDUStallD) oldrd_mdu_stalls = oldrd_mdu_stalls + 1;
        if (dut.core.ieu.c.CSRRdStallD) oldrd_csr_stalls = oldrd_csr_stalls + 1;
      end
      if (dut.core.ieu.c.XrequantE && !dut.core.StallE) begin
        if (dut.core.ieu.c.ForwardAE == 2 || dut.core.ieu.c.ForwardBE == 2) req_forward_m++;
        if (dut.core.ieu.c.ForwardAE == 1 || dut.core.ieu.c.ForwardBE == 1) req_forward_w++;
      end
      if (dut.core.ieu.c.XrequantD) begin
        if (dut.core.ieu.c.LoadStallD) req_load++;
        if (dut.core.ieu.c.MDUStallD) req_mdu++;
        if (dut.core.ieu.c.CSRRdStallD) req_csr++;
      end
      if (dut.core.IllegalXrequantE && !dut.core.StallM && !dut.core.FlushM) descriptor_faults++;
      if (!dut.core.StallE) begin
        if (dut.core.ieu.c.ForwardAE == 3) base_a_m++;
        if (dut.core.ieu.c.ForwardBE == 3) base_b_m++;
        if (dut.core.ieu.c.ForwardCE == 3) base_c_m++;
        if (dut.core.ieu.c.ForwardAE == 4) base_a_w++;
        if (dut.core.ieu.c.ForwardBE == 4) base_b_w++;
        if (dut.core.ieu.c.ForwardCE == 4) base_c_w++;
        if (dut.core.ieu.c.ForwardAE == 3 || dut.core.ieu.c.ForwardBE == 3 || dut.core.ieu.c.ForwardCE == 3) base_forward_m++;
        if (dut.core.ieu.c.ForwardAE == 4 || dut.core.ieu.c.ForwardBE == 4 || dut.core.ieu.c.ForwardCE == 4) base_forward_w++;
      end
      if (dut.core.ieu.c.RegWriteBaseW && !dut.core.StallW) base_writes++;
      if (commit) begin
        retired = retired + 1;
        if ((dut.core.InstrM & 32'hfe007fff) == 32'h0000200b) begin dwmac++; custom++; end
        if ((dut.core.InstrM & 32'hf9f07fff) == 32'h0000300b) begin dwset[dut.core.InstrM[26:25]]++; custom++; end
        if ((dut.core.InstrM & 32'hf9fff07f) == 32'h0000400b) begin dwget[dut.core.InstrM[26:25]]++; custom++; end
        if ((dut.core.InstrM & 32'hfe00707f) == 32'h0000000b) begin qmac++; custom++; end
        if ((dut.core.InstrM & 32'hfe00707f) == 32'h0000100b) begin requant++; custom++; end
        if (dut.core.InstrM[6:0] == 7'h2b) begin postload++; custom++; end
        if (dut.core.InstrM[6:0] == 7'h7b) begin poststore++; custom++; end
        if (dut.core.lsu.MemRWM[0] && dut.core.lsu.IEUAdrM == P.XLEN'(tohost) && store_value[63:48] == 16'h0101) begin
          $write("%c", store_value[7:0]);
          if (store_value[7:0] == 8'd10) $fflush();
        end
        if (dut.core.lsu.MemRWM[0] && dut.core.lsu.IEUAdrM == P.XLEN'(tohost) &&
            store_value[63:48] == 0 && store_value[0]) begin
          if (store_value != 1) $fatal(1, "program self-check failed: %h pc=%h", store_value, dut.core.PCM);
          if (custom != expected_custom || traps != expected_traps || qmac != expected_qmac || requant != expected_requant || postload != expected_postload || poststore != expected_poststore)
            $fatal(1, "count mismatch custom=%0d expected=%0d traps=%0d expected=%0d", custom, expected_custom, traps, expected_traps);
          if (dwmac != expected_dwmac) $fatal(1,"MAC count mismatch %0d != %0d",dwmac,expected_dwmac);
          for (int i=0;i<4;i++)
            if (dwset[i] != expected_dwset[i] || dwget[i] != expected_dwget[i]) $fatal(1,"pair transfer count mismatch pair %0d",i);
          if (irq_pc != 0 && !irq_fired) $fatal(1,"interrupt never reached target");
          $display("XDWMAC8_COVERAGE dwmac=%0d dwset0=%0d dwset1=%0d dwset2=%0d dwset3=%0d dwget0=%0d dwget1=%0d dwget2=%0d dwget3=%0d bank_forward=%0d bank_stall=%0d bank_flush=%0d bank_trap=%0d dw_forward_m=%0d dw_forward_w=%0d dw_load=%0d dw_mdu=%0d dw_csr=%0d irq=%0d",dwmac,dwset[0],dwset[1],dwset[2],dwset[3],dwget[0],dwget[1],dwget[2],dwget[3],bank_forward,bank_stall,bank_flush,bank_trap,dw_forward_m,dw_forward_w,dw_load,dw_mdu,dw_csr,irq_fired);
          $display("XDWMAC8_RTL_PASS cycles=%0d retired=%0d custom=%0d traps=%0d forward_m=%0d forward_w=%0d oldrd_load=%0d oldrd_mdu=%0d oldrd_csr=%0d flushes=%0d",
            cycles, retired, custom, traps, forward_m, forward_w, oldrd_load_stalls, oldrd_mdu_stalls, oldrd_csr_stalls, flushes);
          $display("XREQUANT_COVERAGE qmac=%0d requant=%0d req_forward_m=%0d req_forward_w=%0d req_load=%0d req_mdu=%0d req_csr=%0d descriptor_faults=%0d",
            qmac, requant, req_forward_m, req_forward_w, req_load, req_mdu, req_csr, descriptor_faults);
          $display("XPOSTINC_COVERAGE postload=%0d poststore=%0d base_forward_m=%0d base_forward_w=%0d base_writes=%0d", postload, poststore, base_forward_m, base_forward_w, base_writes);
          $display("XPOSTINC_HAZARDS base_a_m=%0d base_a_w=%0d base_b_m=%0d base_b_w=%0d base_c_m=%0d base_c_w=%0d post_faults=%0d", base_a_m, base_a_w, base_b_m, base_b_w, base_c_m, base_c_w, post_faults);
          $finish;
        end
      end
    end
  end
endmodule
