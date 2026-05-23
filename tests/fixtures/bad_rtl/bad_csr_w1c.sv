module bad_csr_w1c(input logic clk_i, input logic rst_ni, input logic write_i, input logic [31:0] wdata_i, output logic irq_o);
  always_ff @(posedge clk_i) begin
    if (!rst_ni) irq_o <= 1'b0;
    else if (write_i) irq_o <= wdata_i[0];
  end
endmodule