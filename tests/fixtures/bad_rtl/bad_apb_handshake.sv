module bad_apb_handshake(input logic clk_i, input logic rst_ni, input logic psel_i, output logic ready_o);
  always_ff @(posedge clk_i) begin
    if (!rst_ni) ready_o <= 1'b0;
    else ready_o <= psel_i;
  end
endmodule