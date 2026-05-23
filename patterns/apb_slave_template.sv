// AGENT2_PATTERN_ID: apb_slave_template
// Synthesizable APB3 constant-ready register slave micro-template.
module agent2_apb_slave_template #(
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32,
  parameter logic [DATA_WIDTH-1:0] RESET_VALUE = '0
) (
  input  logic                  clk_i,
  input  logic                  rst_ni,
  input  logic                  psel_i,
  input  logic                  penable_i,
  input  logic                  pwrite_i,
  input  logic [ADDR_WIDTH-1:0] paddr_i,
  input  logic [DATA_WIDTH-1:0] pwdata_i,
  output logic [DATA_WIDTH-1:0] prdata_o,
  output logic                  pready_o,
  output logic                  pslverr_o
);
  logic [DATA_WIDTH-1:0] reg0_q;
  logic [DATA_WIDTH-1:0] reg0_d;
  logic [DATA_WIDTH-1:0] prdata_d;
  logic apb_write_access;
  logic apb_read_access;

  assign apb_write_access = psel_i && penable_i && pwrite_i;
  assign apb_read_access = psel_i && penable_i && !pwrite_i;
  assign pready_o = 1'b1;
  assign pslverr_o = 1'b0;

  always_comb begin
    reg0_d = reg0_q;
    prdata_d = reg0_q;
    if (apb_write_access && paddr_i[7:0] == 8'h00) begin
      reg0_d = pwdata_i;
    end else if (apb_read_access && paddr_i[7:0] == 8'h00) begin
      prdata_d = reg0_q;
    end else begin
      prdata_d = RESET_VALUE;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      reg0_q <= RESET_VALUE;
      prdata_o <= RESET_VALUE;
    end else begin
      reg0_q <= reg0_d;
      prdata_o <= prdata_d;
    end
  end
endmodule