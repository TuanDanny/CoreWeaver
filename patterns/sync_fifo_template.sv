// AGENT2_PATTERN_ID: sync_fifo_template
// Synthesizable single-clock FIFO micro-template.
module agent2_sync_fifo_template #(
  parameter int WIDTH = 32,
  parameter int DEPTH = 4,
  parameter int PTR_W = 2
) (
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic             push_i,
  input  logic             pop_i,
  input  logic [WIDTH-1:0] data_i,
  output logic [WIDTH-1:0] data_o,
  output logic             full_o,
  output logic             empty_o
);
  logic [WIDTH-1:0] mem_q [DEPTH];
  logic [PTR_W-1:0] wr_ptr_q;
  logic [PTR_W-1:0] wr_ptr_d;
  logic [PTR_W-1:0] rd_ptr_q;
  logic [PTR_W-1:0] rd_ptr_d;
  logic [PTR_W:0] count_q;
  logic [PTR_W:0] count_d;

  assign full_o = count_q == DEPTH[PTR_W:0];
  assign empty_o = count_q == '0;
  assign data_o = mem_q[rd_ptr_q];

  always_comb begin
    wr_ptr_d = wr_ptr_q;
    rd_ptr_d = rd_ptr_q;
    count_d = count_q;
    if (push_i && !full_o) begin
      wr_ptr_d = wr_ptr_q + 1'b1;
      count_d = count_d + 1'b1;
    end
    if (pop_i && !empty_o) begin
      rd_ptr_d = rd_ptr_q + 1'b1;
      count_d = count_d - 1'b1;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      wr_ptr_q <= '0;
      rd_ptr_q <= '0;
      count_q <= '0;
    end else begin
      wr_ptr_q <= wr_ptr_d;
      rd_ptr_q <= rd_ptr_d;
      count_q <= count_d;
      if (push_i && !full_o) begin
        mem_q[wr_ptr_q] <= data_i;
      end
    end
  end
endmodule