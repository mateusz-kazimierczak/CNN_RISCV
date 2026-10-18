// SPDX-License-Identifier: Apache-2.0
// Independent instances and warm reset while an update is pending.
module bank_tb;
  logic clk=0, r0=1, r1=1, stall=0, flush=0, kill=0;
  logic mac=0, setpair=0, getpair=1;
  logic [1:0] pair=0;
  logic [63:0] source0=123, source1=456, result0, result1;
  logic signed [15:0] products[8];
  xdwmac8 a(clk,r0,stall,flush,kill,mac,setpair,getpair,pair,source0,products,result0);
  xdwmac8 b(clk,r1,stall,flush,kill,mac,setpair,getpair,pair,source1,products,result1);
  task automatic tick;
    #5;clk=1;#1;clk=0;#1;
  endtask
  initial begin
    for(int i=0;i<8;i++)products[i]=-16'sd1;
    tick();r0=0;r1=0;setpair=1;tick();setpair=0;tick();
    if(result0!=123 || result1!=456)$fatal(1,"instances share architectural bank");
    r0=1;tick();r0=0;
    if(result0!=0 || result1!=456)$fatal(1,"warm reset affected wrong instance");
    mac=1;tick(); // both have an uncommitted snapshot
    r0=1;r1=1;tick();mac=0;r0=0;r1=0;tick();
    if(result0!=0 || result1!=0)$fatal(1,"reset retained speculative update");
    setpair=1;stall=1;repeat(5)tick();setpair=0;stall=0;tick();tick();
    if(result0!=0 || result1!=0)$fatal(1,"stalled E operation wrote bank");
    setpair=1;tick();setpair=0;flush=1;kill=1;tick();flush=0;kill=0;tick();
    if(result0!=0 || result1!=0)$fatal(1,"flushed update wrote bank");
    $display("XDWMAC8_BANK_UNIT_PASS instances=2 warm_reset=1 pending_reset=1 stall=1 trap_flush=1");
    $finish;
  end
endmodule
