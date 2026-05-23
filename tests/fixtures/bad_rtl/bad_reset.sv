module bad_reset(input logic clk_i, input logic rst_ni, output logic [3:0] count_o);
  always_ff @(posedge clk_i) begin
    if (!rst_ni) count_o <= 'x;
    else count_o <= count_o + 4'd1;
  end
endmodule