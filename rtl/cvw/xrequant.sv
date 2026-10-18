// SPDX-License-Identifier: Apache-2.0
// Xrequant v1: rounded Q0.31 multiply, then a separate ties-away shift.
// Combinational execute-stage implementation; physical timing is unmeasured.
module xrequant (
  input  logic [63:0] Accumulator, Descriptor,
  output logic [63:0] Result,
  output logic        Illegal
);
  logic signed [31:0] X, Multiplier;
  logic [4:0] Shift;
  logic ScaleOnly;
  logic signed [7:0] ZeroPoint, Lower, Upper;
  logic signed [63:0] Product, Nudged, High, Scaled, Biased;
  logic [63:0] Mask, Remainder, Threshold;

  assign X = $signed(Accumulator[31:0]);
  assign Multiplier = $signed(Descriptor[31:0]);
  assign Shift = Descriptor[36:32];
  assign ZeroPoint = $signed(Descriptor[45:38]);
  assign Lower = $signed(Descriptor[53:46]);
  assign Upper = $signed(Descriptor[61:54]);
  assign ScaleOnly = Descriptor[62];
  assign Illegal = Descriptor[63] || Descriptor[31] || Descriptor[37] ||
                   (Lower > Upper) || (ScaleOnly && (|Descriptor[61:38]));

  // Positive multiplier: the signed product and rounding nudge fit in INT64.
  // This floor-shift identity preserves gemmlowp's signed-nudge/truncation.
  assign Product = X * Multiplier;
  assign Nudged = Product + 64'sd1073741824;
  assign High = Nudged >>> 31;
  assign Mask = (64'd1 << Shift) - 64'd1;
  assign Remainder = $unsigned(High) & Mask;
  assign Threshold = (Mask >> 1) + {63'b0, High[63]};
  assign Scaled = (High >>> Shift) + $signed({63'b0, (Remainder > Threshold)});
  // Keep the zero-point addition wide so INT32 extremes cannot wrap before clip.
  assign Biased = Scaled + {{56{ZeroPoint[7]}}, ZeroPoint};
  always_comb begin
    if (Illegal) Result = '0;
    else if (ScaleOnly) Result = {{32{Scaled[31]}}, Scaled[31:0]};
    else if (Biased < $signed({{56{Lower[7]}}, Lower})) Result = {{56{Lower[7]}}, Lower};
    else if (Biased > $signed({{56{Upper[7]}}, Upper})) Result = {{56{Upper[7]}}, Upper};
    else Result = {{56{Biased[7]}}, Biased[7:0]};
  end
endmodule
