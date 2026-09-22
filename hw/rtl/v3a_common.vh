// -----------------------------------------------------------------------------
// V3A common definitions: signed Q23.40 fixed point in 64 bits
// -----------------------------------------------------------------------------
localparam integer W = 64;          // data width
localparam integer F = 40;          // fraction bits
localparam signed [63:0] FX_ONE   = 64'sh0000_0100_0000_0000;   // 1.0
localparam signed [63:0] FX_THREE = 64'sh0000_0300_0000_0000;   // 3.0

// signed W x W multiply, arithmetic shift right by F, keep W bits
function signed [63:0] fxmul;
  input signed [63:0] a;
  input signed [63:0] b;
  reg   signed [127:0] p;
  begin
    p     = a * b;
    fxmul = p >>> F;
  end
endfunction
