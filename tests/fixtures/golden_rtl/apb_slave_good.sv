`default_nettype none
module apb_slave_good(input logic clk_i, input logic rst_ni, input logic psel_i, input logic penable_i, input logic pwrite_i, input logic [31:0] pwdata_i, output logic pready_o, output logic [31:0] prdata_o);
  logic [31:0] data_q, data_d;
  always_comb begin
    data_d = data_q;
    pready_o = psel_i && penable_i;
    prdata_o = data_q;
    if (psel_i && penable_i && pwrite_i) data_d = pwdata_i;
  end
  always_ff @(posedge clk_i) begin
    if (!rst_ni) data_q <= '0;
    else data_q <= data_d;
  end
endmodule
`default_nettype wire