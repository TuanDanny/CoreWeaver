module compile_order_top_first(input logic clk_i, input logic rst_ni, output logic y_o);
  child u_child(.clk_i(clk_i), .rst_ni(rst_ni), .y_o(y_o));
endmodule