module demo_timer_rtl #(
  parameter int DATA_WIDTH = 32
) (
  input  logic                  clk_i,
  input  logic                  rst_ni,
  input  logic                  psel_i,
  input  logic                  penable_i,
  input  logic                  pwrite_i,
  input  logic [31:0]           paddr_i,
  input  logic [DATA_WIDTH-1:0] pwdata_i,
  output logic [DATA_WIDTH-1:0] prdata_o,
  output logic                  pready_o,
  output logic                  pslverr_o
);
  assign pready_o = 1'b0;
  assign pslverr_o = 1'b0;
  always_ff @(posedge clk_i) begin
    if (!rst_ni) prdata_o <= '0;
  end
endmodule
