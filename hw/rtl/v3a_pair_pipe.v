// -----------------------------------------------------------------------------
// v3a_pair_pipe: nbody pairwise-gravity kernel, fully pipelined, latency 19
//
//   inputs : positions of bodies i and j, m_i*dt, m_j*dt, body indices
//   outputs: f_i = d*(m_j*dt)*|d|^-3   (host/controller: v_i -= f_i)
//            f_j = d*(m_i*dt)*|d|^-3   (                 v_j += f_j)
//   with d = r_i - r_j. Same math as advance() in bm_nbody.
//
//   P1   d = r_i - r_j                         (3 subtractors)
//   P2   dx^2, dy^2, dz^2                      (3 multipliers)
//   P3   d2 = dx^2 + dy^2 + dz^2
//   P4.. 12-stage v3a_invsqrt:  y = d2^-1/2    (sideband delayed 12 stages)
//   P16  y2  = y*y
//   P17  mag = y2*y            = d2^-3/2
//   P18  b1m = mdt_i*mag, b2m = mdt_j*mag
//   P19  f_i = d*b2m, f_j = d*b1m              (6 multipliers)
// -----------------------------------------------------------------------------
module v3a_pair_pipe #(
  parameter integer IW = 4                     // body index width
) (
  input  wire               clk,
  input  wire               rst,
  input  wire               valid_i,
  input  wire [IW-1:0]      bi_i,
  input  wire [IW-1:0]      bj_i,
  input  wire signed [63:0] xi, yi, zi,
  input  wire signed [63:0] xj, yj, zj,
  input  wire signed [63:0] mdti, mdtj,
  output wire               valid_o,
  output wire [IW-1:0]      bi_o,
  output wire [IW-1:0]      bj_o,
  output wire signed [63:0] fix, fiy, fiz,
  output wire signed [63:0] fjx, fjy, fjz
);
  `include "v3a_common.vh"
  localparam integer SBW = 2 + 2*IW + 5*64;   // sideband: valid, idx, d, mdt

  // P1 ------------------------------------------------------------------------
  reg               v1;
  reg [IW-1:0]      i1, j1;
  reg signed [63:0] dx1, dy1, dz1, mi1, mj1;
  always @(posedge clk) begin
    v1 <= rst ? 1'b0 : valid_i;
    i1 <= bi_i; j1 <= bj_i;
    dx1 <= xi - xj; dy1 <= yi - yj; dz1 <= zi - zj;
    mi1 <= mdti; mj1 <= mdtj;
  end

  // P2 ------------------------------------------------------------------------
  reg               v2;
  reg [IW-1:0]      i2, j2;
  reg signed [63:0] dx2, dy2, dz2, mi2, mj2, sx2, sy2, sz2;
  always @(posedge clk) begin
    v2 <= rst ? 1'b0 : v1;
    i2 <= i1; j2 <= j1; dx2 <= dx1; dy2 <= dy1; dz2 <= dz1; mi2 <= mi1; mj2 <= mj1;
    sx2 <= fxmul(dx1, dx1); sy2 <= fxmul(dy1, dy1); sz2 <= fxmul(dz1, dz1);
  end

  // P3 ------------------------------------------------------------------------
  reg               v3;
  reg [IW-1:0]      i3, j3;
  reg signed [63:0] dx3, dy3, dz3, mi3, mj3, d2_3;
  always @(posedge clk) begin
    v3 <= rst ? 1'b0 : v2;
    i3 <= i2; j3 <= j2; dx3 <= dx2; dy3 <= dy2; dz3 <= dz2; mi3 <= mi2; mj3 <= mj2;
    d2_3 <= sx2 + sy2 + sz2;
  end

  // P4..P15: inverse square root + balanced sideband ----------------------------
  wire               vq;
  wire signed [63:0] yq;
  v3a_invsqrt u_isqrt (.clk(clk), .rst(rst), .valid_i(v3), .x_i(d2_3), .valid_o(vq), .y_o(yq));

  wire [SBW-1:0] sb_in = {1'b0, v3, i3, j3, dx3, dy3, dz3, mi3, mj3};
  wire [SBW-1:0] sb_q;
  v3a_delay #(.WIDTH(SBW), .N(12)) u_sb (.clk(clk), .rst(rst), .d(sb_in), .q(sb_q));
  wire               sv;
  wire [IW-1:0]      si, sj;
  wire signed [63:0] sdx, sdy, sdz, smi, smj;
  wire               unused_bit;
  assign {unused_bit, sv, si, sj, sdx, sdy, sdz, smi, smj} = sb_q;

  // P16 -----------------------------------------------------------------------
  reg               v16;
  reg [IW-1:0]      i16, j16;
  reg signed [63:0] dx16, dy16, dz16, mi16, mj16, y16, yy16;
  always @(posedge clk) begin
    v16 <= rst ? 1'b0 : vq;
    i16 <= si; j16 <= sj; dx16 <= sdx; dy16 <= sdy; dz16 <= sdz; mi16 <= smi; mj16 <= smj;
    y16 <= yq; yy16 <= fxmul(yq, yq);
  end

  // P17 -----------------------------------------------------------------------
  reg               v17;
  reg [IW-1:0]      i17, j17;
  reg signed [63:0] dx17, dy17, dz17, mi17, mj17, mag17;
  always @(posedge clk) begin
    v17 <= rst ? 1'b0 : v16;
    i17 <= i16; j17 <= j16; dx17 <= dx16; dy17 <= dy16; dz17 <= dz16; mi17 <= mi16; mj17 <= mj16;
    mag17 <= fxmul(yy16, y16);
  end

  // P18 -----------------------------------------------------------------------
  reg               v18;
  reg [IW-1:0]      i18, j18;
  reg signed [63:0] dx18, dy18, dz18, b1m18, b2m18;
  always @(posedge clk) begin
    v18 <= rst ? 1'b0 : v17;
    i18 <= i17; j18 <= j17; dx18 <= dx17; dy18 <= dy17; dz18 <= dz17;
    b1m18 <= fxmul(mi17, mag17);
    b2m18 <= fxmul(mj17, mag17);
  end

  // P19 -----------------------------------------------------------------------
  reg               v19;
  reg [IW-1:0]      i19, j19;
  reg signed [63:0] fix19, fiy19, fiz19, fjx19, fjy19, fjz19;
  always @(posedge clk) begin
    v19 <= rst ? 1'b0 : v18;
    i19 <= i18; j19 <= j18;
    fix19 <= fxmul(dx18, b2m18); fiy19 <= fxmul(dy18, b2m18); fiz19 <= fxmul(dz18, b2m18);
    fjx19 <= fxmul(dx18, b1m18); fjy19 <= fxmul(dy18, b1m18); fjz19 <= fxmul(dz18, b1m18);
  end

  assign valid_o = v19;
  assign bi_o = i19;  assign bj_o = j19;
  assign fix = fix19; assign fiy = fiy19; assign fiz = fiz19;
  assign fjx = fjx19; assign fjy = fjy19; assign fjz = fjz19;
endmodule
