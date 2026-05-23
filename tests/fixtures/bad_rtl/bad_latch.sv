module bad_latch(input logic a_i, input logic b_i, output logic y_o);
  always_latch begin
    if (a_i) y_o = b_i;
  end
endmodule