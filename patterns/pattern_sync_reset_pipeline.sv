// AGENT2_PATTERN_ID: pattern_sync_reset_pipeline
// Synthesizable q/d pipeline skeleton with synchronous active-low reset.
module pattern_sync_reset_pipeline #(
  parameter int DATA_WIDTH = 32,
  parameter logic [DATA_WIDTH-1:0] RESET_VALUE = '0
) (
  input  logic                  clk_i,
  input  logic                  rst_ni,
  input  logic [DATA_WIDTH-1:0] data_i,
  input  logic                  valid_i,
  output logic [DATA_WIDTH-1:0] data_o,
  output logic                  valid_o
);
  logic [DATA_WIDTH-1:0] stage_1_data_q;
  logic [DATA_WIDTH-1:0] stage_1_data_d;
  logic                  stage_1_valid_q;
  logic                  stage_1_valid_d;

  always_comb begin
    stage_1_data_d = stage_1_data_q;
    stage_1_valid_d = 1'b0;
    if (valid_i) begin
      stage_1_data_d = data_i;
      stage_1_valid_d = 1'b1;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      stage_1_data_q <= RESET_VALUE;
      stage_1_valid_q <= 1'b0;
    end else begin
      stage_1_data_q <= stage_1_data_d;
      stage_1_valid_q <= stage_1_valid_d;
    end
  end

  assign data_o = stage_1_data_q;
  assign valid_o = stage_1_valid_q;
endmodule