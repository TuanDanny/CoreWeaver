// AGENT2_PATTERN_ID: interrupt_controller_w1c_sticky
module interrupt_controller_w1c_sticky #(
  parameter int SOURCES = 8
) (
  input  logic               clk_i,
  input  logic               rst_ni,
  input  logic [SOURCES-1:0] irq_raw_i,
  input  logic [SOURCES-1:0] irq_mask_i,
  input  logic [SOURCES-1:0] irq_w1c_i,
  output logic [SOURCES-1:0] irq_status_o,
  output logic               irq_o
);
  logic [SOURCES-1:0] sticky_q, sticky_d;

  assign irq_status_o = sticky_q;
  assign irq_o = |(sticky_q & irq_mask_i);

  always_comb begin
    sticky_d = sticky_q;
    sticky_d = sticky_d | irq_raw_i;
    sticky_d = sticky_d & ~irq_w1c_i;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      sticky_q <= '0;
    end else begin
      sticky_q <= sticky_d;
    end
  end
endmodule