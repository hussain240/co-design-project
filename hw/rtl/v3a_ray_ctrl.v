// -----------------------------------------------------------------------------
// v3a_ray_ctrl: batched ray-sphere queries (closest hit / any hit) in hardware
//
// Register map (word offsets inside the ray window; BAR offset = 8*index)
//   0x00000 CTRL     W  bit0 = start, bit1 = mode (0 closest hit, 1 any hit)
//   0x00001 STATUS   R  bit0 = busy, bit1 = done
//   0x00002 NRAYS    RW number of rays      (1..RMAX)
//   0x00003 NSPH     RW number of spheres   (1..SMAX)
//   0x00004 EPS      RW epsilon, Q23.40     (benchmark: 1e-5)
//   0x00005 CYCLES   R  clock cycles spent busy
//   0x00006 TESTS    R  ray-sphere tests completed
//   0x00100 + 4*s + f   RW sphere s: 0 cx, 1 cy, 2 cz, 3 radius^2
//   0x10000 + 8*r + f   W  ray r:    0 px, 1 py, 2 pz, 3 dx, 4 dy, 5 dz (d normalized)
//   0x80000 + 2*r + f   R  result r: 0 index (closest: sphere or -1; any: 1/0), 1 t
//
// Rays live in a BRAM (one 384-bit word per ray, synchronous read, byte-write
// style field update) = the DMA buffer the host fills before START.
// All NRAYS*NSPH tests are streamed through v3a_raysphere_pipe, one per cycle;
// a reducer after the pipeline keeps the per-ray best hit and writes the result.
// -----------------------------------------------------------------------------
module v3a_ray_ctrl #(
  parameter integer RMAX = 4096,
  parameter integer SMAX = 16,
  parameter integer RW   = 16,
  parameter integer SW   = 8
) (
  input  wire        clk,
  input  wire        rst,
  input  wire [19:0] addr,
  input  wire [63:0] wdata,
  input  wire        we,
  output reg  [63:0] rdata,
  output wire        done_irq
);
  `include "v3a_common.vh"

  localparam [1:0] S_IDLE = 2'd0, S_FEED = 2'd1, S_WAIT = 2'd2;

  reg [1:0]  state;
  reg        mode, done;
  reg [63:0] nrays, nsph, cycles, tests;
  reg signed [63:0] eps;

  reg [383:0]       RAYM [0:RMAX-1];
  reg signed [63:0] SCX [0:SMAX-1], SCY [0:SMAX-1], SCZ [0:SMAX-1], SR2 [0:SMAX-1];
  reg signed [63:0] RES_I [0:RMAX-1], RES_T [0:RMAX-1];

  wire busy = (state != S_IDLE);
  assign done_irq = done;

  // ---------------- feed: (r,s) pointer -> BRAM read -> pipeline ----------------------
  reg [RW-1:0] fr;  reg [SW-1:0] fs;          // feed pointer
  reg          fv;                             // pointer valid this cycle
  reg [RW-1:0] fr_d; reg [SW-1:0] fs_d; reg fv_d;
  reg [383:0]  ray_q;
  always @(posedge clk) begin
    ray_q <= RAYM[fr];                         // synchronous BRAM read
    fr_d  <= fr; fs_d <= fs;
    fv_d  <= rst ? 1'b0 : fv;
  end

  wire               ov;
  wire [RW-1:0]      orid;
  wire [SW-1:0]      osid;
  wire signed [63:0] odisc, ot;
  v3a_raysphere_pipe #(.RW(RW), .SW(SW)) u_pipe (
    .clk(clk), .rst(rst), .valid_i(fv_d), .rid_i(fr_d), .sid_i(fs_d),
    .px(ray_q[0 +: 64]), .py(ray_q[64 +: 64]), .pz(ray_q[128 +: 64]),
    .dx(ray_q[192 +: 64]), .dy(ray_q[256 +: 64]), .dz(ray_q[320 +: 64]),
    .cx(SCX[fs_d]), .cy(SCY[fs_d]), .cz(SCZ[fs_d]), .r2(SR2[fs_d]),
    .valid_o(ov), .rid_o(orid), .sid_o(osid), .disc_o(odisc), .t_o(ot));

  // ---------------- reducer ------------------------------------------------------------
  reg signed [63:0] cur_i, cur_t;
  wire               first = (osid == 0);
  wire               last  = (osid == nsph[SW-1:0] - 1);
  wire signed [63:0] base_i = first ? -64'sd1 : cur_i;
  wire signed [63:0] base_t = first ? 64'sd0  : cur_t;
  wire               hit_c  = (odisc >= 0) && (ot > -eps);     // closest-hit candidate
  wire               hit_a  = (odisc >= 0) && (ot >  eps);     // occluder
  wire               take   = hit_c && (base_i < 0 || ot < base_t);
  wire signed [63:0] new_i  = mode ? ((first ? 64'sd0 : cur_i) | {63'd0, hit_a})
                                   : (take ? $signed({{(64-SW){1'b0}}, osid}) : base_i);
  wire signed [63:0] new_t  = mode ? 64'sd0 : (take ? ot : base_t);

  // ---------------- host register read -------------------------------------------------
  wire [19:0] soff = addr - 20'h00100;
  wire [19:0] roff = addr - 20'h10000;
  wire [19:0] qoff = addr - 20'h80000;
  always @(*) begin
    rdata = 64'd0;
    if      (addr == 20'h00001) rdata = {62'd0, done, busy};
    else if (addr == 20'h00002) rdata = nrays;
    else if (addr == 20'h00003) rdata = nsph;
    else if (addr == 20'h00004) rdata = eps;
    else if (addr == 20'h00005) rdata = cycles;
    else if (addr == 20'h00006) rdata = tests;
    else if (addr >= 20'h00100 && addr < 20'h00100 + 4*SMAX)
      case (soff[1:0])
        2'd0: rdata = SCX[soff[19:2]]; 2'd1: rdata = SCY[soff[19:2]];
        2'd2: rdata = SCZ[soff[19:2]]; 2'd3: rdata = SR2[soff[19:2]];
      endcase
    else if (addr >= 20'h80000 && addr < 20'h80000 + 2*RMAX)
      rdata = qoff[0] ? RES_T[qoff[19:1]] : RES_I[qoff[19:1]];
  end

  // ---------------- control FSM ---------------------------------------------------------
  always @(posedge clk) begin
    if (rst) begin
      state <= S_IDLE; done <= 1'b0; mode <= 1'b0;
      nrays <= 0; nsph <= 0; eps <= 0; cycles <= 0; tests <= 0;
      fr <= 0; fs <= 0; fv <= 1'b0; cur_i <= -1; cur_t <= 0;
    end else begin
      if (busy) cycles <= cycles + 1;

      if (ov) begin
        cur_i <= new_i;
        cur_t <= new_t;
        tests <= tests + 1;
        if (last) begin RES_I[orid] <= new_i; RES_T[orid] <= new_t; end
      end

      case (state)
        S_IDLE: begin
          fv <= 1'b0;
          if (we) begin
            if (addr == 20'h00000 && wdata[0]) begin
              mode <= wdata[1]; done <= 1'b0; cycles <= 0; tests <= 0;
              fr <= 0; fs <= 0;
              if (nrays == 0 || nsph == 0) done <= 1'b1;
              else begin fv <= 1'b1; state <= S_FEED; end
            end
            else if (addr == 20'h00002) nrays <= wdata;
            else if (addr == 20'h00003) nsph  <= wdata;
            else if (addr == 20'h00004) eps   <= wdata;
            else if (addr >= 20'h00100 && addr < 20'h00100 + 4*SMAX)
              case (soff[1:0])
                2'd0: SCX[soff[19:2]] <= wdata; 2'd1: SCY[soff[19:2]] <= wdata;
                2'd2: SCZ[soff[19:2]] <= wdata; 2'd3: SR2[soff[19:2]] <= wdata;
              endcase
            else if (addr >= 20'h10000 && addr < 20'h10000 + 8*RMAX)
              RAYM[roff[19:3]][roff[2:0]*64 +: 64] <= wdata;
          end
        end

        S_FEED: begin                                   // advance (r,s) every cycle
          if (fs == nsph[SW-1:0] - 1) begin
            fs <= 0;
            if (fr == nrays[RW-1:0] - 1) begin fv <= 1'b0; state <= S_WAIT; end
            else fr <= fr + 1;
          end else
            fs <= fs + 1;
        end

        S_WAIT: if (tests == nrays * nsph) begin state <= S_IDLE; done <= 1'b1; end

        default: state <= S_IDLE;
      endcase
    end
  end
endmodule
