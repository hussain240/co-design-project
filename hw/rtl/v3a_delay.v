// -----------------------------------------------------------------------------
// v3a_delay: N-stage shift register (pipeline balancing for sideband signals)
// -----------------------------------------------------------------------------
module v3a_delay #(
  parameter integer WIDTH = 1,
  parameter integer N     = 1
) (
  input  wire             clk,
  input  wire             rst,
  input  wire [WIDTH-1:0] d,
  output wire [WIDTH-1:0] q
);
  reg [WIDTH-1:0] sr [0:N-1];
  integer i;
  always @(posedge clk) begin
    if (rst) begin
      for (i = 0; i < N; i = i + 1) sr[i] <= {WIDTH{1'b0}};
    end else begin
      sr[0] <= d;
      for (i = 1; i < N; i = i + 1) sr[i] <= sr[i-1];
    end
  end
  assign q = sr[N-1];
endmodule
