module registered_adder (
  input logic clk,
  input logic reset,
  input logic [31:0] a, b,
  output logic [31:0] sum
);
  always_ff @(posedge clk)
    if (reset) sum <= 32'b0;
    else sum <= a + b;
endmodule
