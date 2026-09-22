// -----------------------------------------------------------------------------
// v3a_raysphere_pipe: ray-sphere intersection kernel, fully pipelined, latency 19
//
//   inputs : ray origin p, normalized direction d, sphere centre c, radius^2
//   outputs: disc (hit iff disc >= 0) and t = v - sqrt(disc)
//   Same math as Sphere.intersectionTime() in bm_raytrace.
//
//   R1   e = c - p                                    (3 subtractors)
//   R2   ex*dx, ey*dy, ez*dz, ex^2, ey^2, ez^2        (6 multipliers)
//   R3   v = e.d ,  cc = e.e
//   R4   vv = v*v
//   R5   disc = r2 - (cc - vv)
//   R6.. 12-stage v3a_invsqrt: y = disc^-1/2          (sideband delayed 12 stages)
//   R18  s = disc*y  (= sqrt(disc))
//   R19  t = v - s
// -----------------------------------------------------------------------------
module v3a_raysphere_pipe #(
  parameter integer RW = 16,                   // ray id width
  parameter integer SW = 8                     // sphere id width
) (
  input  wire               clk,
  input  wire               rst,
  input  wire               valid_i,
  input  wire [RW-1:0]      rid_i,
  input  wire [SW-1:0]      sid_i,
  input  wire signed [63:0] px, py, pz,
  input  wire signed [63:0] dx, dy, dz,
  input  wire signed [63:0] cx, cy, cz, r2,
  output wire               valid_o,
  output wire [RW-1:0]      rid_o,
  output wire [SW-1:0]      sid_o,
  output wire signed [63:0] disc_o,
  output wire signed [63:0] t_o
);
  `include "v3a_common.vh"
  localparam integer SBW = 1 + RW + SW + 2*64;  // sideband: valid, ids, v, disc

  // R1 ------------------------------------------------------------------------
  reg               v1;
  reg [RW-1:0]      r1;  reg [SW-1:0] s1;
  reg signed [63:0] ex1, ey1, ez1, dx1, dy1, dz1, rr1;
  always @(posedge clk) begin
    v1 <= rst ? 1'b0 : valid_i;
    r1 <= rid_i; s1 <= sid_i;
    ex1 <= cx - px; ey1 <= cy - py; ez1 <= cz - pz;
    dx1 <= dx; dy1 <= dy; dz1 <= dz; rr1 <= r2;
  end

  // R2 ------------------------------------------------------------------------
  reg               v2;
  reg [RW-1:0]      r2r; reg [SW-1:0] s2;
  reg signed [63:0] a2x, a2y, a2z, c2x, c2y, c2z, rr2;
  always @(posedge clk) begin
    v2 <= rst ? 1'b0 : v1;
    r2r <= r1; s2 <= s1; rr2 <= rr1;
    a2x <= fxmul(ex1, dx1); a2y <= fxmul(ey1, dy1); a2z <= fxmul(ez1, dz1);
    c2x <= fxmul(ex1, ex1); c2y <= fxmul(ey1, ey1); c2z <= fxmul(ez1, ez1);
  end

  // R3 ------------------------------------------------------------------------
  reg               v3;
  reg [RW-1:0]      r3;  reg [SW-1:0] s3;
  reg signed [63:0] vv3, cc3, rr3;
  always @(posedge clk) begin
    v3 <= rst ? 1'b0 : v2;
    r3 <= r2r; s3 <= s2; rr3 <= rr2;
    vv3 <= a2x + a2y + a2z;
    cc3 <= c2x + c2y + c2z;
  end

  // R4 ------------------------------------------------------------------------
  reg               v4;
  reg [RW-1:0]      r4;  reg [SW-1:0] s4;
  reg signed [63:0] v_4, cc4, rr4, sq4;
  always @(posedge clk) begin
    v4 <= rst ? 1'b0 : v3;
    r4 <= r3; s4 <= s3; v_4 <= vv3; cc4 <= cc3; rr4 <= rr3;
    sq4 <= fxmul(vv3, vv3);
  end

  // R5 ------------------------------------------------------------------------
  reg               v5;
  reg [RW-1:0]      r5;  reg [SW-1:0] s5;
  reg signed [63:0] v_5, disc5;
  always @(posedge clk) begin
    v5 <= rst ? 1'b0 : v4;
    r5 <= r4; s5 <= s4; v_5 <= v_4;
    disc5 <= rr4 - (cc4 - sq4);
  end

  // R6..R17: inverse square root + balanced sideband ----------------------------
  wire               vq;
  wire signed [63:0] yq;
  v3a_invsqrt u_isqrt (.clk(clk), .rst(rst), .valid_i(v5), .x_i(disc5), .valid_o(vq), .y_o(yq));

  wire [SBW-1:0] sb_q;
  v3a_delay #(.WIDTH(SBW), .N(12)) u_sb (.clk(clk), .rst(rst),
                                         .d({v5, r5, s5, v_5, disc5}), .q(sb_q));
  wire               sv;
  wire [RW-1:0]      sr;  wire [SW-1:0] ss;
  wire signed [63:0] sV, sD;
  assign {sv, sr, ss, sV, sD} = sb_q;

  // R18 -----------------------------------------------------------------------
  reg               v18;
  reg [RW-1:0]      r18; reg [SW-1:0] s18;
  reg signed [63:0] V18, D18, S18;
  always @(posedge clk) begin
    v18 <= rst ? 1'b0 : vq;
    r18 <= sr; s18 <= ss; V18 <= sV; D18 <= sD;
    S18 <= fxmul(sD, yq);
  end

  // R19 -----------------------------------------------------------------------
  reg               v19;
  reg [RW-1:0]      r19; reg [SW-1:0] s19;
  reg signed [63:0] D19, T19;
  always @(posedge clk) begin
    v19 <= rst ? 1'b0 : v18;
    r19 <= r18; s19 <= s18; D19 <= D18;
    T19 <= V18 - S18;
  end

  assign valid_o = v19;
  assign rid_o = r19;  assign sid_o = s19;
  assign disc_o = D19; assign t_o = T19;
endmodule
