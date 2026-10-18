// SPDX-License-Identifier: Apache-2.0
// Shared signed INT8 multipliers for Xqmac8 and the independent depthwise lanes.
module xmac8_products (
  input logic [63:0] A, B,
  output logic signed [15:0] Products [8]
);
  for (genvar i = 0; i < 8; i++) begin : lanes
    assign Products[i] = $signed(A[8*i +: 8]) * $signed(B[8*i +: 8]);
  end
endmodule

module xqmac8_reduce (
  input logic signed [15:0] Products [8],
  input logic [63:0] Accumulator,
  output logic [63:0] Result
);
  logic signed [16:0] Pairs [4];
  logic signed [17:0] Quads [2];
  logic signed [18:0] Dot;
  logic [31:0] Sum;
  for (genvar i = 0; i < 4; i++) begin : pairs
    assign Pairs[i] = {Products[2*i][15], Products[2*i]} +
                      {Products[2*i+1][15], Products[2*i+1]};
  end
  for (genvar i = 0; i < 2; i++) begin : quads
    assign Quads[i] = {Pairs[2*i][16], Pairs[2*i]} +
                      {Pairs[2*i+1][16], Pairs[2*i+1]};
  end
  assign Dot = {Quads[0][17], Quads[0]} + {Quads[1][17], Quads[1]};
  assign Sum = Accumulator[31:0] + {{13{Dot[18]}}, Dot};
  assign Result = {{32{Sum[31]}}, Sum};
endmodule

// The bank is architectural at the M->W acceptance edge, after trap checks.
// Forward an entire pending snapshot so back-to-back set/MAC/get operations
// see all older writes. Speculative E/M snapshots are cleared by ordinary flushes.
module xdwmac8 (
  input logic clk, reset, StallM, FlushM, FlushW,
  input logic MacE, SetE, GetE,
  input logic [1:0] PairE,
  input logic [63:0] SourceE,
  input logic signed [15:0] ProductsE [8],
  output logic [63:0] ResultE
);
  logic [255:0] Bank, VisibleE, NextE, NextM;
  logic WriteM;
  assign VisibleE = WriteM ? NextM : Bank;
  assign ResultE = GetE ? VisibleE[64*PairE +: 64] : 64'b0;
  always_comb begin
    NextE = VisibleE;
    if (MacE)
      for (int i = 0; i < 8; i++)
        NextE[32*i +: 32] = VisibleE[32*i +: 32] +
                            {{16{ProductsE[i][15]}}, ProductsE[i]};
    else if (SetE) NextE[64*PairE +: 64] = SourceE;
  end
  flopenrc #(257) pending(clk, reset, FlushM, ~StallM,
                          {MacE | SetE, NextE}, {WriteM, NextM});
  always_ff @(posedge clk) begin
    if (reset) Bank <= '0;
    else if (WriteM && !StallM && !FlushW) Bank <= NextM;
  end
endmodule
