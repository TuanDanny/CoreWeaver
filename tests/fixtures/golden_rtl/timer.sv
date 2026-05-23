`default_nettype none
module timer(input logic clk_i, input logic rst_ni, input logic enable_i, output logic irq_o);
  logic [7:0] counter_q, counter_d;
  always_comb begin counter_d = counter_q + {7'd0, enable_i}; irq_o = &counter_q; end
  always_ff @(posedge clk_i) begin
    if (!rst_ni) counter_q <= '0;
    else counter_q <= counter_d;
  end
endmodule
`default_nettype wire