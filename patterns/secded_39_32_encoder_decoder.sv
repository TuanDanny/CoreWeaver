// AGENT2_PATTERN_ID: secded_39_32_encoder_decoder
module secded_39_32_encoder_decoder (
  input  logic        clk_i,
  input  logic        rst_ni,
  input  logic [31:0] data_i,
  input  logic [38:0] code_i,
  output logic [38:0] code_o,
  output logic [31:0] data_o,
  output logic [6:0]  syndrome_o,
  output logic        correctable_error_o,
  output logic        uncorrectable_error_o
);
  logic [6:0] parity_d;
  logic [6:0] syndrome_d;
  logic [6:0] syndrome_q;

  always_comb begin
    parity_d[0] = ^data_i[7:0];
    parity_d[1] = ^data_i[15:8];
    parity_d[2] = ^data_i[23:16];
    parity_d[3] = ^data_i[31:24];
    parity_d[4] = ^data_i[15:0];
    parity_d[5] = ^data_i[31:16];
    parity_d[6] = ^{data_i, parity_d[5:0]};
    code_o = {parity_d, data_i};
    syndrome_d = code_i[38:32] ^ parity_d;
    syndrome_o = syndrome_d;
    data_o = code_i[31:0];
    correctable_error_o = |syndrome_d && syndrome_d[6];
    uncorrectable_error_o = |syndrome_d && !syndrome_d[6];
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      syndrome_q <= '0;
    end else begin
      syndrome_q <= syndrome_d;
    end
  end
endmodule