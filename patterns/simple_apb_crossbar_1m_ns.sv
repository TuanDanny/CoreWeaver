// AGENT2_PATTERN_ID: simple_apb_crossbar_1m_ns
module simple_apb_crossbar_1m_ns #(
  parameter int SLAVES = 4,
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic                    psel_i,
  input  logic                    penable_i,
  input  logic                    pwrite_i,
  input  logic [ADDR_WIDTH-1:0]   paddr_i,
  input  logic [DATA_WIDTH-1:0]   pwdata_i,
  input  logic [SLAVES-1:0][DATA_WIDTH-1:0] slave_prdata_i,
  input  logic [SLAVES-1:0]       slave_pready_i,
  input  logic [SLAVES-1:0]       slave_pslverr_i,
  output logic [SLAVES-1:0]       slave_psel_o,
  output logic                    slave_penable_o,
  output logic                    slave_pwrite_o,
  output logic [ADDR_WIDTH-1:0]   slave_paddr_o,
  output logic [DATA_WIDTH-1:0]   slave_pwdata_o,
  output logic [DATA_WIDTH-1:0]   prdata_o,
  output logic                    pready_o,
  output logic                    pslverr_o
);
  logic [$clog2(SLAVES)-1:0] select_q, select_d;
  logic decode_hit;

  assign slave_penable_o = penable_i;
  assign slave_pwrite_o = pwrite_i;
  assign slave_paddr_o = paddr_i;
  assign slave_pwdata_o = pwdata_i;

  always_comb begin
    slave_psel_o = '0;
    select_d = paddr_i[13:12];
    decode_hit = (paddr_i[15:14] == 2'b00);
    prdata_o = '0;
    pready_o = 1'b1;
    pslverr_o = 1'b0;
    if (psel_i && decode_hit) begin
      slave_psel_o[select_d] = 1'b1;
      prdata_o = slave_prdata_i[select_d];
      pready_o = slave_pready_i[select_d];
      pslverr_o = slave_pslverr_i[select_d];
    end else if (psel_i) begin
      pslverr_o = 1'b1;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      select_q <= '0;
    end else begin
      select_q <= select_d;
    end
  end
endmodule