`default_nettype none
module sram_controller(input logic clk_i, input logic rst_ni, input logic req_i, input logic we_i, input logic [31:0] addr_i, output logic ready_o, output logic [31:0] rdata_o);
  always_comb begin ready_o = req_i; rdata_o = addr_i; end
endmodule
`default_nettype wire