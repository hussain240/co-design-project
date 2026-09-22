// -----------------------------------------------------------------------------
// v3a_top: V3A 3D Vector-math Accelerator (PCIe endpoint core logic)
//
// Host interface: memory-mapped register bus (models PCIe BAR0 behind an
// AXI4-Lite bridge). Word-addressed, 64-bit data:
//   0x000000 .. 0x0FFFFF   nbody kernel window   (v3a_nbody_ctrl)
//   0x100000 .. 0x1FFFFF   ray kernel window     (v3a_ray_ctrl)
// irq: level interrupt when either kernel has finished (MSI in a real system).
//
// Both kernels share the same arithmetic IP (v3a_invsqrt, Q23.40 multipliers)
// and the same streaming pipeline style.
// -----------------------------------------------------------------------------
module v3a_top (
  input  wire        clk,
  input  wire        rst,
  input  wire [23:0] addr,
  input  wire [63:0] wdata,
  input  wire        we,
  output wire [63:0] rdata,
  output wire        irq
);
  wire sel_ray = addr[20];
  wire [63:0] rd_nb, rd_ray;
  wire        irq_nb, irq_ray;

  v3a_nbody_ctrl u_nbody (
    .clk(clk), .rst(rst), .addr(addr[19:0]), .wdata(wdata), .we(we & ~sel_ray),
    .rdata(rd_nb), .done_irq(irq_nb));

  v3a_ray_ctrl u_ray (
    .clk(clk), .rst(rst), .addr(addr[19:0]), .wdata(wdata), .we(we & sel_ray),
    .rdata(rd_ray), .done_irq(irq_ray));

  assign rdata = sel_ray ? rd_ray : rd_nb;
  assign irq   = irq_nb | irq_ray;
endmodule
