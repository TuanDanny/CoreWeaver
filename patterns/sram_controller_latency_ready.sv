// AGENT2_PATTERN_ID: sram_controller_latency_ready
module sram_controller_latency_ready #(
  parameter int ADDR_WIDTH = 10,
  parameter int DATA_WIDTH = 32,
  parameter int DEPTH = 1024
) (
  input  logic                  clk_i,
  input  logic                  rst_ni,
  input  logic                  req_i,
  input  logic                  we_i,
  input  logic [ADDR_WIDTH-1:0] addr_i,
  input  logic [DATA_WIDTH-1:0] wdata_i,
  output logic [DATA_WIDTH-1:0] rdata_o,
  output logic                  ready_o
);
  logic [DATA_WIDTH-1:0] mem_q [DEPTH];
  logic [DATA_WIDTH-1:0] rdata_q, rdata_d;
  logic ready_q, ready_d;

  assign rdata_o = rdata_q;
  assign ready_o = ready_q;

  always_comb begin
    rdata_d = rdata_q;
    ready_d = 1'b0;
    if (req_i) begin
      ready_d = 1'b1;
      if (!we_i) rdata_d = mem_q[addr_i];
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      rdata_q <= '0;
      ready_q <= 1'b0;
    end else begin
      if (req_i && we_i) mem_q[addr_i] <= wdata_i;
      rdata_q <= rdata_d;
      ready_q <= ready_d;
    end
  end
endmodule