// -----------------------------------------------------------------------------
// v3a_invsqrt: pipelined y = 1/sqrt(x), signed Q23.40, latency 12 clock cycles
//
//   stage 1      normalize: x = m * 4^k with m in [1,4)  (priority encoder + shift)
//   stage 2      initial guess y0 = ROM[m[41:36]]         (64-entry ROM)
//   stages 3-11  3 Newton iterations, 3 stages each:
//                  y2 = y*y ;  t = m*y2 ;  y = y*(3 - t)/2
//   stage 12     denormalize: y = y / 2^k
//
// Every stage contains at most ONE 64x64 multiplier. x <= 0 gives a
// don't-care result (valid_o still follows valid_i; callers ignore it).
// Throughput: one result per clock cycle (fully pipelined).
// -----------------------------------------------------------------------------
module v3a_invsqrt (
  input  wire               clk,
  input  wire               rst,
  input  wire               valid_i,
  input  wire signed [63:0] x_i,
  output wire               valid_o,
  output wire signed [63:0] y_o
);
  `include "v3a_common.vh"
  `include "v3a_invsqrt_lut.vh"

  localparam integer ITERS = 3;
  localparam integer NS    = 3 * ITERS;      // Newton pipeline stages

  // index of the leading one of a positive number
  function [6:0] msb_index;
    input [63:0] v;
    integer n;
    begin
      msb_index = 7'd0;
      for (n = 0; n < 64; n = n + 1)
        if (v[n]) msb_index = n[6:0];
    end
  endfunction

  // ---------------- stage 1: normalize ----------------------------------------
  wire               x_pos = (x_i > 0);
  wire signed [7:0]  e     = $signed({1'b0, msb_index(x_i)}) - 8'sd40;
  wire signed [7:0]  k_c   = x_pos ? (e >>> 1) : 8'sd0;
  wire        [7:0]  sh_r  = k_c[7] ? 8'd0 : (k_c << 1);
  wire        [7:0]  sh_l  = k_c[7] ? ((-k_c) << 1) : 8'd0;
  wire signed [63:0] m_c   = x_pos ? (k_c[7] ? (x_i <<< sh_l) : (x_i >>> sh_r)) : FX_ONE;

  reg               v1;
  reg signed [63:0] m1;
  reg signed [7:0]  k1;
  always @(posedge clk) begin
    v1 <= rst ? 1'b0 : valid_i;
    m1 <= m_c;
    k1 <= k_c;
  end

  // ---------------- stage 2: initial guess from ROM ---------------------------
  reg               v2;
  reg signed [63:0] m2, y2r;
  reg signed [7:0]  k2;
  always @(posedge clk) begin
    v2  <= rst ? 1'b0 : v1;
    m2  <= m1;
    k2  <= k1;
    y2r <= lut_rom(m1[41:36]);
  end

  // ---------------- stages 3..11: Newton iterations ---------------------------
  // pipeline registers after Newton stage g are at index g+1 (1..NS)
  reg               nv [1:NS];
  reg signed [63:0] ny [1:NS];      // current estimate y
  reg signed [63:0] nt [1:NS];      // scratch (y*y, then m*y*y)
  reg signed [63:0] nm [1:NS];
  reg signed [7:0]  nk [1:NS];

  genvar g;
  generate
    for (g = 0; g < NS; g = g + 1) begin : newton
      // stage inputs: stage 2 registers for the first Newton stage
      wire               vin;
      wire signed [63:0] yin, tin, min;
      wire signed [7:0]  kin;
      if (g == 0) begin : first
        assign vin = v2;    assign yin = y2r;   assign tin = 64'sd0;
        assign min = m2;    assign kin = k2;
      end else begin : next
        assign vin = nv[g]; assign yin = ny[g]; assign tin = nt[g];
        assign min = nm[g]; assign kin = nk[g];
      end
      always @(posedge clk) begin
        nv[g+1] <= rst ? 1'b0 : vin;
        nm[g+1] <= min;
        nk[g+1] <= kin;
        case (g % 3)
          0: begin ny[g+1] <= yin; nt[g+1] <= fxmul(yin, yin); end              // y*y
          1: begin ny[g+1] <= yin; nt[g+1] <= fxmul(min, tin); end              // m*y*y
          2: begin ny[g+1] <= fxmul(yin, FX_THREE - tin) >>> 1;                 // y(3-t)/2
                   nt[g+1] <= 64'sd0; end
        endcase
      end
    end
  endgenerate

  // ---------------- stage 12: denormalize --------------------------------------
  reg               vo;
  reg signed [63:0] yo;
  wire signed [7:0] kf = nk[NS];
  wire        [7:0] dl = kf[7] ? (-kf) : 8'd0;
  wire        [7:0] dr = kf[7] ? 8'd0  : kf;
  always @(posedge clk) begin
    vo <= rst ? 1'b0 : nv[NS];
    yo <= kf[7] ? (ny[NS] <<< dl) : (ny[NS] >>> dr);
  end

  assign valid_o = vo;
  assign y_o     = yo;
endmodule
