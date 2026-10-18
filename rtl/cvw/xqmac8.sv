// SPDX-License-Identifier: Apache-2.0
// Eight signed byte products, accumulated modulo 2^32 into old rd.
// Combinational E-stage implementation. Timing/area require synthesis.
module xqmac8 (
  input  logic [63:0] A, B, Accumulator,
  output logic [63:0] Result
);
  logic signed [15:0] Products [8];
  logic signed [16:0] Pairs [4];
  logic signed [17:0] Quads [2];
  logic signed [18:0] Dot;
  logic [31:0] Sum;
  for (genvar i = 0; i < 8; i++) begin : lanes
    assign Products[i] = $signed(A[8*i +: 8]) * $signed(B[8*i +: 8]);
  end
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
