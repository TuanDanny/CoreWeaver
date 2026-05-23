// AGENT2_PATTERN_ID: apb_timer_counter
module apb_timer_counter #(
  parameter int ADDR_WIDTH = 12,
  parameter int DATA_WIDTH = 32
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
  output logic                  pslverr_o,
  output logic                  irq_o
);
  logic [DATA_WIDTH-1:0] count_q, count_d;
  logic [DATA_WIDTH-1:0] compare_q, compare_d;
  logic enable_q, enable_d;
  logic irq_q, irq_d;
  logic apb_access;

  assign apb_access = psel_i && penable_i;
  assign pready_o = 1'b1;
  assign irq_o = irq_q;

  always_comb begin
    count_d = count_q;
    compare_d = compare_q;
    enable_d = enable_q;
    irq_d = irq_q;
    prdata_o = '0;
    pslverr_o = 1'b0;
    if (enable_q) begin
      count_d = count_q + 1'b1;
      if (count_q == compare_q) irq_d = 1'b1;
    end
    if (apb_access) begin
      unique case (paddr_i[3:2])
        2'd0: begin
          prdata_o = count_q;
          if (pwrite_i) count_d = pwdata_i;
        end
        2'd1: begin
          prdata_o = compare_q;
          if (pwrite_i) compare_d = pwdata_i;
        end
        2'd2: begin
          prdata_o = {{(DATA_WIDTH-1){1'b0}}, enable_q};
          if (pwrite_i) enable_d = pwdata_i[0];
        end
        2'd3: begin
          prdata_o = {{(DATA_WIDTH-1){1'b0}}, irq_q};
          if (pwrite_i && pwdata_i[0]) irq_d = 1'b0;
        end
        default: pslverr_o = 1'b1;
      endcase
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      count_q <= '0;
      compare_q <= '0;
      enable_q <= 1'b0;
      irq_q <= 1'b0;
    end else begin
      count_q <= count_d;
      compare_q <= compare_d;
      enable_q <= enable_d;
      irq_q <= irq_d;
    end
  end
endmodule