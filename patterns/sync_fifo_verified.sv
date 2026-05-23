// AGENT2_PATTERN_ID: sync_fifo_verified
module sync_fifo_verified #(
  parameter int WIDTH = 32,
  parameter int DEPTH = 4,
  localparam int ADDR_W = (DEPTH <= 2) ? 1 : $clog2(DEPTH + 1)
) (
  input  logic             clk_i,
  input  logic             rst_ni,
  input  logic             push_i,
  input  logic             pop_i,
  input  logic [WIDTH-1:0] data_i,
  output logic [WIDTH-1:0] data_o,
  output logic             full_o,
  output logic             empty_o,
  output logic [ADDR_W-1:0] count_o
);
  logic [WIDTH-1:0] mem_q [DEPTH];
  logic [WIDTH-1:0] mem_d [DEPTH];
  logic [ADDR_W-1:0] wr_ptr_q, wr_ptr_d;
  logic [ADDR_W-1:0] rd_ptr_q, rd_ptr_d;
  logic [ADDR_W-1:0] count_q, count_d;
  logic do_push;
  logic do_pop;

  assign full_o  = (count_q == DEPTH[ADDR_W-1:0]);
  assign empty_o = (count_q == '0);
  assign data_o  = mem_q[rd_ptr_q];
  assign count_o = count_q;
  assign do_push = push_i && !full_o;
  assign do_pop  = pop_i && !empty_o;

  always_comb begin
    mem_d = mem_q;
    wr_ptr_d = wr_ptr_q;
    rd_ptr_d = rd_ptr_q;
    count_d = count_q;
    if (do_push) begin
      mem_d[wr_ptr_q] = data_i;
      wr_ptr_d = (wr_ptr_q == DEPTH[ADDR_W-1:0] - 1'b1) ? '0 : wr_ptr_q + 1'b1;
    end
    if (do_pop) begin
      rd_ptr_d = (rd_ptr_q == DEPTH[ADDR_W-1:0] - 1'b1) ? '0 : rd_ptr_q + 1'b1;
    end
    unique case ({do_push, do_pop})
      2'b10: count_d = count_q + 1'b1;
      2'b01: count_d = count_q - 1'b1;
      default: count_d = count_q;
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      wr_ptr_q <= '0;
      rd_ptr_q <= '0;
      count_q <= '0;
      mem_q <= '{default: '0};
    end else begin
      wr_ptr_q <= wr_ptr_d;
      rd_ptr_q <= rd_ptr_d;
      count_q <= count_d;
      mem_q <= mem_d;
    end
  end
endmodule