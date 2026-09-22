// -----------------------------------------------------------------------------
// v3a_nbody_ctrl: runs N_STEPS complete nbody time steps in hardware
//
// Register map (word offsets inside the nbody window; BAR offset = 8*index)
//   0x000 CTRL      W  bit0 = start
//   0x001 STATUS    R  bit0 = busy, bit1 = done (sticky until next start)
//   0x002 NBODIES   RW number of bodies (2..NMAX)
//   0x003 NSTEPS    RW number of time steps to run
//   0x004 DT        RW time step, Q23.40
//   0x005 STEPDONE  R  completed steps
//   0x006 CYCLES    R  clock cycles spent busy (performance counter)
//   0x007 ID        R  64'h5633_415f_4e42_4f44 ("V3A_NBOD")
//   0x100 + 8*k + f RW body k, field f: 0 x, 1 y, 2 z, 3 vx, 4 vy, 5 vz, 6 m*dt
//
// One step (all pair forces use the positions at the start of the step):
//   FEED  : stream all N(N-1)/2 pairs (i<j) into v3a_pair_pipe, one per cycle
//   WAIT  : accumulate outputs:  acc_i -= f_i ; acc_j += f_j
//   VEL   : v_k += acc_k                       (all bodies in parallel)
//   POS   : r_k += dt * v_k                    (one body per cycle, 3 multipliers)
// -----------------------------------------------------------------------------
module v3a_nbody_ctrl #(
  parameter integer NMAX = 8,
  parameter integer IW   = 4
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

  localparam [2:0] S_IDLE = 3'd0, S_CLR = 3'd1, S_FEED = 3'd2, S_WAIT = 3'd3,
                   S_VEL  = 3'd4, S_POS = 3'd5, S_NEXT = 3'd6;

  reg [2:0]  state;
  reg [63:0] nbodies, nsteps, dt, stepdone, cycles;
  reg        done;

  reg signed [63:0] BX [0:NMAX-1], BY [0:NMAX-1], BZ [0:NMAX-1];
  reg signed [63:0] VX [0:NMAX-1], VY [0:NMAX-1], VZ [0:NMAX-1];
  reg signed [63:0] MD [0:NMAX-1];
  reg signed [63:0] AX [0:NMAX-1], AY [0:NMAX-1], AZ [0:NMAX-1];

  reg [IW-1:0] pi, pj, pk;             // feed pair (pi,pj), position-update body pk
  reg [15:0]   npairs, sent, recv;

  wire busy = (state != S_IDLE);
  assign done_irq = done;

  // ---------------- pair pipeline ------------------------------------------------
  wire               feed = (state == S_FEED);
  wire               ov;
  wire [IW-1:0]      oi, oj;
  wire signed [63:0] fix, fiy, fiz, fjx, fjy, fjz;
  v3a_pair_pipe #(.IW(IW)) u_pipe (
    .clk(clk), .rst(rst), .valid_i(feed), .bi_i(pi), .bj_i(pj),
    .xi(BX[pi]), .yi(BY[pi]), .zi(BZ[pi]), .xj(BX[pj]), .yj(BY[pj]), .zj(BZ[pj]),
    .mdti(MD[pi]), .mdtj(MD[pj]),
    .valid_o(ov), .bi_o(oi), .bj_o(oj),
    .fix(fix), .fiy(fiy), .fiz(fiz), .fjx(fjx), .fjy(fjy), .fjz(fjz));

  // ---------------- host register read ---------------------------------------------
  wire [19:0] boff = addr - 20'h100;
  wire [15:0] bk   = boff[19:3];
  wire [2:0]  bf   = boff[2:0];
  always @(*) begin
    rdata = 64'd0;
    case (addr)
      20'h001: rdata = {62'd0, done, busy};
      20'h002: rdata = nbodies;
      20'h003: rdata = nsteps;
      20'h004: rdata = dt;
      20'h005: rdata = stepdone;
      20'h006: rdata = cycles;
      20'h007: rdata = 64'h5633_415f_4e42_4f44;
      default:
        if (addr >= 20'h100 && bk < NMAX)
          case (bf)
            3'd0: rdata = BX[bk]; 3'd1: rdata = BY[bk]; 3'd2: rdata = BZ[bk];
            3'd3: rdata = VX[bk]; 3'd4: rdata = VY[bk]; 3'd5: rdata = VZ[bk];
            3'd6: rdata = MD[bk]; default: rdata = 64'd0;
          endcase
    endcase
  end

  // ---------------- control FSM + datapath registers --------------------------------
  integer k;
  always @(posedge clk) begin
    if (rst) begin
      state <= S_IDLE; done <= 1'b0;
      nbodies <= 0; nsteps <= 0; dt <= 0; stepdone <= 0; cycles <= 0;
      pi <= 0; pj <= 0; pk <= 0; npairs <= 0; sent <= 0; recv <= 0;
    end else begin
      if (busy) cycles <= cycles + 1;

      // accumulate pipeline outputs (any state; only occurs during a step)
      if (ov) begin
        AX[oi] <= AX[oi] - fix;  AY[oi] <= AY[oi] - fiy;  AZ[oi] <= AZ[oi] - fiz;
        AX[oj] <= AX[oj] + fjx;  AY[oj] <= AY[oj] + fjy;  AZ[oj] <= AZ[oj] + fjz;
        recv <= recv + 1;
      end

      case (state)
        S_IDLE: begin
          if (we) begin                                   // host access only when idle
            case (addr)
              20'h000: if (wdata[0]) begin
                         done <= 1'b0; stepdone <= 0; cycles <= 0;
                         npairs <= (nbodies * (nbodies - 1)) >> 1;
                         state <= (nsteps == 0 || nbodies < 2) ? S_IDLE : S_CLR;
                         if (nsteps == 0 || nbodies < 2) done <= 1'b1;
                       end
              20'h002: nbodies <= wdata;
              20'h003: nsteps  <= wdata;
              20'h004: dt      <= wdata;
              default:
                if (addr >= 20'h100 && bk < NMAX)
                  case (bf)
                    3'd0: BX[bk] <= wdata; 3'd1: BY[bk] <= wdata; 3'd2: BZ[bk] <= wdata;
                    3'd3: VX[bk] <= wdata; 3'd4: VY[bk] <= wdata; 3'd5: VZ[bk] <= wdata;
                    3'd6: MD[bk] <= wdata; default: ;
                  endcase
            endcase
          end
        end

        S_CLR: begin                                      // start of a time step
          for (k = 0; k < NMAX; k = k + 1) begin AX[k] <= 0; AY[k] <= 0; AZ[k] <= 0; end
          pi <= 0; pj <= 1; sent <= 0; recv <= 0;
          state <= S_FEED;
        end

        S_FEED: begin                                     // one pair per cycle
          sent <= sent + 1;
          if (pj == nbodies - 1) begin pi <= pi + 1; pj <= pi + 2; end
          else                         pj <= pj + 1;
          if (sent + 1 == npairs) state <= S_WAIT;
        end

        S_WAIT: if (recv == npairs) state <= S_VEL;

        S_VEL: begin
          for (k = 0; k < NMAX; k = k + 1) begin
            VX[k] <= VX[k] + AX[k]; VY[k] <= VY[k] + AY[k]; VZ[k] <= VZ[k] + AZ[k];
          end
          pk <= 0;
          state <= S_POS;
        end

        S_POS: begin
          BX[pk] <= BX[pk] + fxmul(dt, VX[pk]);
          BY[pk] <= BY[pk] + fxmul(dt, VY[pk]);
          BZ[pk] <= BZ[pk] + fxmul(dt, VZ[pk]);
          pk <= pk + 1;
          if (pk == nbodies - 1) state <= S_NEXT;
        end

        S_NEXT: begin
          stepdone <= stepdone + 1;
          if (stepdone + 1 == nsteps) begin state <= S_IDLE; done <= 1'b1; end
          else                                state <= S_CLR;
        end

        default: state <= S_IDLE;
      endcase
    end
  end
endmodule
