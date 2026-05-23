`default_nettype none
module interrupt_ctrl(input logic clk_i, input logic rst_ni, input logic set_i, input logic w1c_i, output logic irq_o);
  logic irq_d;
  always_comb begin
    irq_d = irq_o | set_i;
    if (w1c_i) irq_d = 1'b0;
  end
  always_ff @(posedge clk_i) begin
    if (!rst_ni) irq_o <= 1'b0;
    else irq_o <= irq_d;
  end
endmodule
`default_nettype wire