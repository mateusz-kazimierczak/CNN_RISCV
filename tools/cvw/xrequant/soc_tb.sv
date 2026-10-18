// SPDX-License-Identifier: Apache-2.0
// Real CV-Wally SoC, its caches, privilege/trap machinery and AHB RAM.
// Architectural test programs check their own results; the host observes exit.
`include "config.vh"
import cvw::*;
module xrequant_soc_tb;
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
    $readmemh(image, dut.uncoregen.uncore.ram.ram.memory.ram.RAM);
    repeat (8) @(negedge clk);
    reset_ext = 0;
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
      if (commit) begin
        retired = retired + 1;
        if ((dut.core.InstrM & 32'hfe00707f) == 32'h0000000b) begin qmac++; custom++; end
        if ((dut.core.InstrM & 32'hfe00707f) == 32'h0000100b) begin requant++; custom++; end
        if (dut.core.lsu.MemRWM[0] && dut.core.lsu.IEUAdrM == P.XLEN'(tohost) && store_value[63:48] == 16'h0101)
          $write("%c", store_value[7:0]);
        if (dut.core.lsu.MemRWM[0] && dut.core.lsu.IEUAdrM == P.XLEN'(tohost) &&
            store_value[63:48] == 0 && store_value[0]) begin
          if (store_value != 1) $fatal(1, "program self-check failed: %h pc=%h", store_value, dut.core.PCM);
          if (custom != expected_custom || traps != expected_traps || qmac != expected_qmac || requant != expected_requant)
            $fatal(1, "count mismatch custom=%0d expected=%0d traps=%0d expected=%0d", custom, expected_custom, traps, expected_traps);
          $display("XREQUANT_RTL_PASS cycles=%0d retired=%0d custom=%0d traps=%0d forward_m=%0d forward_w=%0d oldrd_load=%0d oldrd_mdu=%0d oldrd_csr=%0d flushes=%0d",
            cycles, retired, custom, traps, forward_m, forward_w, oldrd_load_stalls, oldrd_mdu_stalls, oldrd_csr_stalls, flushes);
          $display("XREQUANT_COVERAGE qmac=%0d requant=%0d req_forward_m=%0d req_forward_w=%0d req_load=%0d req_mdu=%0d req_csr=%0d descriptor_faults=%0d",
            qmac, requant, req_forward_m, req_forward_w, req_load, req_mdu, req_csr, descriptor_faults);
          $finish;
        end
      end
    end
  end
endmodule
