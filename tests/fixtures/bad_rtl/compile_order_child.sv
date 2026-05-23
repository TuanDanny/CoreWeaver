module child(input logic clk_i, input logic rst_ni, output logic y_o);
  always_ff @(posedge clk_i) begin
    if (!rst_ni) y_o <= 1'b0;
    else y_o <= 1'b1;
  end
endmodule