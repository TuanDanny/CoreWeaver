"""Rule-based Agent 2 prototype for synthesizable SystemVerilog generation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORBIDDEN_RTL_TOKENS = ("$display", "#delay", "initial begin", " reg ", " wire ")
QUALITY_RULES = (
    "module_header",
    "apb_pinout_locked",
    "logic_ports",
    "clk_reset_present",
    "always_ff_present",
    "always_comb_present",
    "fsm_enum_present",
    "q_d_pipeline_naming",
    "no_forbidden_rtl_tokens",
    "outputs_driven",
    "top_instantiates_all_blocks",
    "top_wires_interrupts",
    "apb_template_marker_present",
)

from semiconductor_swarm.agents.agent2_rtl.contracts import APB_SLAVE_INTERFACE, validate_agent2_architecture_spec
from semiconductor_swarm.contracts.validators import agent1_to_agent2_spec
from semiconductor_swarm.agents.agent2_rtl.orchestrator import run_agent2_orchestrator
from semiconductor_swarm.agents.agent2_rtl.pattern_library import pattern_manifest
from semiconductor_swarm.agents.agent2_rtl.rag_stub import retrieve_agent2_context
from semiconductor_swarm.agents.agent2_rtl.rtl_linter import lint_rtl_files
from semiconductor_swarm.tools.quartus_runner import create_quartus_project_files, run_quartus_compile


@dataclass(frozen=True)
class RTLFile:
    filename: str
    language: str
    content: str
    line_count: int
    dependencies: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "language": self.language,
            "content": self.content,
            "line_count": self.line_count,
            "dependencies": self.dependencies,
        }


def generate_rtl_files(spec: dict[str, Any], *, debug: bool = False) -> list[dict[str, Any]]:
    """Generate JSON-compatible RTL file entries from an Agent 1 spec.

    Set ``debug=True`` to append a machine-readable self-check report proving
    which Agent 2 prompt rules were verified for the generated RTL.
    """
    return run_agent2_orchestrator(spec, debug=debug, legacy_generator=_generate_legacy_rtl_files)


def _generate_legacy_rtl_files(spec: dict[str, Any], debug: bool = False) -> list[dict[str, Any]]:
    """Existing deterministic RTL generator kept as Milestone A backend."""
    validate_agent2_architecture_spec(spec)
    spec = agent1_to_agent2_spec(spec)
    if spec["interfaces"].get("apb_slave") != APB_SLAVE_INTERFACE:
        raise ValueError("Agent 2 refuses specs with renamed APB slave ports")
    if spec["constraints"].get("agent2_port_renaming_allowed") is not False:
        raise ValueError("Agent 2 requires port renaming to be disabled")

    rag_context = retrieve_agent2_context(spec)
    project = spec["project_name"]
    blocks = [block["name"] for block in spec["ip_blocks"]]
    data_width = int(spec.get("bus_topology", {}).get("data_width_bits", 32))
    files: list[RTLFile] = []
    for block in blocks:
        files.append(_file(f"{block}_pkg.sv", _pkg(project, block), []))
        files.append(_file(f"{block}_intf.sv", _intf(block), []))
        files.append(_file(f"{block}.sv", _rtl(project, block, spec), [f"{block}_pkg.sv"]))
    files.append(_file(f"{project}_top.sv", _top(project, blocks, data_width), [f"{block}.sv" for block in blocks]))
    result = [file.as_dict() for file in files]
    report = verify_rtl_files(spec, result)
    if not report["pass"]:
        raise ValueError(f"Generated RTL failed Agent 2 self-check: {report['failures']}")
    if debug:
        report["rag_context"] = rag_context
        result.append(_debug_report_file(report).as_dict())
    return result


def apply_agent2_fix_request(spec: dict[str, Any], rtl_files: list[dict[str, Any]], fix_request: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply orchestrator fix request to RTL before next Agent 5/3/4 pass."""
    validate_agent2_architecture_spec(spec)
    spec = agent1_to_agent2_spec(spec)
    fix_type = fix_request.get("fix_type")
    if fix_type != "PIPELINE_CRITICAL_PATH":
        return rtl_files
    return [_pipeline_critical_path_file(file, fix_request) if file.get("language") == "systemverilog" else file for file in rtl_files]


def prepare_rtl_for_quartus(spec: dict[str, Any], rtl_files: list[dict[str, Any]], work_dir: str | Path) -> dict[str, str]:
    """Agent 2 handoff tool: write RTL and Quartus project files for real synthesis."""
    validate_agent2_architecture_spec(spec)
    spec = agent1_to_agent2_spec(spec)
    paths = create_quartus_project_files(
        spec["project_name"],
        f"{spec['project_name']}_top",
        rtl_files,
        work_dir,
        target_mhz=float(spec["core_config"]["frequency_mhz"]),
    )
    return {key: str(path) for key, path in paths.items()}


def synthesize_rtl_with_quartus(
    spec: dict[str, Any],
    rtl_files: list[dict[str, Any]],
    work_dir: str | Path,
    *,
    quartus_sh: str = "quartus_sh",
    require_quartus: bool = True,
) -> dict[str, Any]:
    """Agent 2 tool: run `quartus_sh --flow compile` and return real compile metrics."""
    validate_agent2_architecture_spec(spec)
    spec = agent1_to_agent2_spec(spec)
    result = run_quartus_compile(
        spec["project_name"],
        f"{spec['project_name']}_top",
        rtl_files,
        work_dir,
        target_mhz=float(spec["core_config"]["frequency_mhz"]),
        quartus_sh=quartus_sh,
        require_quartus=require_quartus,
    )
    return result.as_dict()


def _pkg(project: str, block: str) -> str:
    return f"""package {project}_{block}_pkg;
  parameter int ADDR_WIDTH = 32;
  parameter int DATA_WIDTH = 32;
  parameter logic [DATA_WIDTH-1:0] RESET_VALUE = '0;

  typedef enum logic [1:0] {{
    S_IDLE,
    S_SETUP,
    S_ACCESS
  }} state_t;

  typedef struct packed {{
    logic [ADDR_WIDTH-1:0] addr;
    logic [DATA_WIDTH-1:0] wdata;
    logic                  write;
  }} apb_req_t;
endpackage
"""


def _intf(block: str) -> str:
    return f"""interface {block}_intf #(
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32
);
  logic                  psel_i;     // APB slave select
  logic                  penable_i;  // APB access phase indicator
  logic                  pwrite_i;   // APB write enable
  logic [ADDR_WIDTH-1:0] paddr_i;    // APB byte address
  logic [DATA_WIDTH-1:0] pwdata_i;   // APB write data
  logic [DATA_WIDTH-1:0] prdata_o;   // APB read data
  logic                  pready_o;   // APB ready response
  logic                  pslverr_o;  // APB error response

  modport slave (
    input  psel_i,
    input  penable_i,
    input  pwrite_i,
    input  paddr_i,
    input  pwdata_i,
    output prdata_o,
    output pready_o,
    output pslverr_o
  );
endinterface
"""


def _rtl(project: str, block: str, spec: dict[str, Any] | None = None) -> str:
    registers = _block_registers(spec or {}, block)
    if registers:
        return _register_bank_rtl(project, block, registers)
    irq_port_comma = ""
    mac_ports = ""
    mac_logic = ""
    irq_logic = "\n  assign irq_o = 1'b0; // No interrupt source for this block"
    if block == "mac_array":
        irq_port_comma = ","
        mac_ports = """
  output logic [31:0] mac_result_o, // Last accumulated MAC result
  output logic        mac_valid_o   // Result valid pulse"""
        irq_logic = "\n  assign irq_o = stage_1_valid_q; // Interrupt on MAC valid pulse"
        mac_logic = """

  logic [31:0] stage_1_acc_q;
  logic [31:0] stage_1_acc_d;
  logic        stage_1_valid_q;
  logic        stage_1_valid_d;
  logic [32:0] stage_1_sum;    // 33-bit intermediate for overflow detection

  assign stage_1_sum = {1'b0, stage_1_acc_q} + {1'b0, pwdata_i};

  always_comb begin
    stage_1_acc_d = stage_1_acc_q;
    stage_1_valid_d = 1'b0;
    if (apb_write_access && paddr_i[7:0] == 8'h10) begin
      // Saturate at MAX_VAL on overflow instead of wrapping
      stage_1_acc_d = stage_1_sum[32] ? 32'hFFFF_FFFF : stage_1_sum[31:0];
      stage_1_valid_d = 1'b1;
    end else begin
      stage_1_acc_d = stage_1_acc_q;
    end
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      stage_1_acc_q <= '0;
      stage_1_valid_q <= 1'b0;
    end else begin
      stage_1_acc_q <= stage_1_acc_d;
      stage_1_valid_q <= stage_1_valid_d;
    end
  end

  assign mac_result_o = stage_1_acc_q;
  assign mac_valid_o = stage_1_valid_q;"""
    return f"""// AGENT2_PATTERN_ID: apb_slave_template
// GOLDEN_PATTERN: apb_register_slave
// GOLDEN_PATTERN: q_d_ff_pipeline
// GOLDEN_PATTERN: fsm_enum
module {project}_{block}_rtl #(
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32,
  parameter logic [DATA_WIDTH-1:0] RESET_VALUE = '0
) (
  input  logic                  clk_i,     // Clock input
  input  logic                  rst_ni,    // Active-low synchronous reset
  input  logic                  psel_i,    // APB slave select
  input  logic                  penable_i, // APB access phase indicator
  input  logic                  pwrite_i,  // APB write enable
  input  logic [ADDR_WIDTH-1:0] paddr_i,   // APB byte address
  input  logic [DATA_WIDTH-1:0] pwdata_i,  // APB write data
  output logic [DATA_WIDTH-1:0] prdata_o,  // APB read data
  output logic                  pready_o,  // APB ready response
  output logic                  pslverr_o, // APB error response
  output logic                  irq_o{irq_port_comma}      // Interrupt request
  {mac_ports}
);
  typedef enum logic [1:0] {{
    S_IDLE,
    S_SETUP,
    S_ACCESS
  }} state_t;

  state_t state_q;
  state_t state_d;
  logic [DATA_WIDTH-1:0] reg0_q;
  logic [DATA_WIDTH-1:0] reg0_d;
  logic [DATA_WIDTH-1:0] prdata_d;
  logic apb_write_access;
  logic apb_read_access;

  assign apb_write_access = psel_i && penable_i && pwrite_i;
  assign apb_read_access  = psel_i && penable_i && !pwrite_i;
  assign pready_o = 1'b1;
  assign pslverr_o = 1'b0;{irq_logic}

  always_comb begin
    state_d = state_q;
    reg0_d = reg0_q;
    prdata_d = reg0_q;
    unique case (state_q)
      S_IDLE: begin
        if (psel_i && !penable_i) begin
          state_d = S_SETUP;
        end else begin
          state_d = S_IDLE;
        end
      end
      S_SETUP: begin
        if (psel_i && penable_i) begin
          state_d = S_ACCESS;
        end else begin
          state_d = S_IDLE;
        end
      end
      S_ACCESS: begin
        if (psel_i) begin
          state_d = S_SETUP;
        end else begin
          state_d = S_IDLE;
        end
        if (apb_write_access) begin
          unique case (paddr_i[7:0])
            8'h00: reg0_d = pwdata_i;
            default: reg0_d = reg0_q;
          endcase
        end else if (apb_read_access) begin
          unique case (paddr_i[7:0])
            8'h00: prdata_d = reg0_q;
            default: prdata_d = RESET_VALUE;
          endcase
        end else begin
          prdata_d = reg0_q;
        end
      end
      default: state_d = S_IDLE;
    endcase
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q <= S_IDLE;
      reg0_q <= RESET_VALUE;
      prdata_o <= RESET_VALUE;
    end else begin
      state_q <= state_d;
      reg0_q <= reg0_d;
      prdata_o <= prdata_d;
    end
  end{mac_logic}
endmodule
"""

def _block_registers(spec: dict[str, Any], block: str) -> dict[str, dict[str, Any]]:
    entry = spec.get("memory_map", {}).get(block, {})
    registers = entry.get("registers", {}) if isinstance(entry, dict) else {}
    return registers if isinstance(registers, dict) else {}

def _sv_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name).lower()

def _access(meta: dict[str, Any], reg_name: str) -> str:
    access = str(meta.get("access", "")).lower()
    if access in {"rw", "ro", "wo", "w1c"}:
        return access
    if meta.get("clear") == "W1C":
        return "w1c"
    if "status" in reg_name:
        return "ro"
    return "rw"

def _register_bank_rtl(project: str, block: str, registers: dict[str, dict[str, Any]]) -> str:
    reg_items = [(name, meta) for name, meta in registers.items()]
    declarations = []
    reset_lines = []
    defaults = []
    write_cases = []
    read_cases = []
    for name, meta in reg_items:
        sv = _sv_name(name)
        offset = int(str(meta.get("offset", "0x00")), 0)
        reset = str(meta.get("reset", "0"))
        access = _access(meta, name)
        declarations.append(f"  logic [DATA_WIDTH-1:0] {sv}_q;")
        declarations.append(f"  logic [DATA_WIDTH-1:0] {sv}_d;")
        reset_lines.append(f"      {sv}_q <= {reset};")
        defaults.append(f"    {sv}_d = {sv}_q;")
        if access == "w1c":
            write_cases.append(f"            8'h{offset:02X}: {sv}_d = {sv}_q & ~pwdata_i;")
        elif access != "ro":
            write_cases.append(f"            8'h{offset:02X}: {sv}_d = pwdata_i;")
        if access == "wo":
            read_cases.append(f"            8'h{offset:02X}: prdata_d = RESET_VALUE;")
        else:
            read_cases.append(f"            8'h{offset:02X}: prdata_d = {sv}_q;")
    update_lines = [f"      {_sv_name(name)}_q <= {_sv_name(name)}_d;" for name, _meta in reg_items]
    irq_logic = "1'b0"
    if "irq_status" in registers and "irq_enable" in registers:
        irq_logic = "|(irq_status_q & irq_enable_q)"
    return f"""// AGENT2_PATTERN_ID: apb_slave_template
// GOLDEN_PATTERN: apb_register_slave
// GOLDEN_PATTERN: q_d_ff_pipeline
// GOLDEN_PATTERN: fsm_enum
module {project}_{block}_rtl #(
  parameter int ADDR_WIDTH = 32,
  parameter int DATA_WIDTH = 32,
  parameter logic [DATA_WIDTH-1:0] RESET_VALUE = '0
) (
  input  logic                  clk_i,     // Clock input
  input  logic                  rst_ni,    // Active-low synchronous reset
  input  logic                  psel_i,    // APB slave select
  input  logic                  penable_i, // APB access phase indicator
  input  logic                  pwrite_i,  // APB write enable
  input  logic [ADDR_WIDTH-1:0] paddr_i,   // APB byte address
  input  logic [DATA_WIDTH-1:0] pwdata_i,  // APB write data
  output logic [DATA_WIDTH-1:0] prdata_o,  // APB read data
  output logic                  pready_o,  // APB ready response
  output logic                  pslverr_o, // APB error response
  output logic                  irq_o      // Interrupt request
);
  typedef enum logic [1:0] {{
    S_IDLE,
    S_SETUP,
    S_ACCESS
  }} state_t;

  state_t state_q;
  state_t state_d;
{chr(10).join(declarations)}
  logic [DATA_WIDTH-1:0] prdata_d;
  logic apb_write_access;
  logic apb_read_access;
  logic illegal_addr_d;
  logic pslverr_q;

  assign apb_write_access = psel_i && penable_i && pwrite_i;
  assign apb_read_access  = psel_i && penable_i && !pwrite_i;
  assign pready_o = 1'b1;
  assign pslverr_o = pslverr_q;
  assign irq_o = {irq_logic};

  always_comb begin
    state_d = state_q;
{chr(10).join(defaults)}
    prdata_d = RESET_VALUE;
    illegal_addr_d = 1'b0;
    unique case (state_q)
      S_IDLE: begin
        if (psel_i && !penable_i) begin
          state_d = S_SETUP;
        end else begin
          state_d = S_IDLE;
        end
      end
      S_SETUP: begin
        if (psel_i && penable_i) begin
          state_d = S_ACCESS;
        end else begin
          state_d = S_IDLE;
        end
      end
      S_ACCESS: begin
        if (psel_i) begin
          state_d = S_SETUP;
        end else begin
          state_d = S_IDLE;
        end
        if (apb_write_access) begin
          unique case (paddr_i[7:0])
{chr(10).join(write_cases) if write_cases else "            default: ;"}
            default: illegal_addr_d = 1'b1;
          endcase
        end else if (apb_read_access) begin
          unique case (paddr_i[7:0])
{chr(10).join(read_cases)}
            default: begin
              prdata_d = RESET_VALUE;
              illegal_addr_d = 1'b1;
            end
          endcase
        end
      end
      default: state_d = S_IDLE;
    endcase
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q <= S_IDLE;
{chr(10).join(reset_lines)}
      prdata_o <= RESET_VALUE;
      pslverr_q <= 1'b0;
    end else begin
      state_q <= state_d;
{chr(10).join(update_lines)}
      prdata_o <= prdata_d;
      pslverr_q <= illegal_addr_d;
    end
  end
endmodule
"""


def _top(project: str, blocks: list[str], data_width: int = 32) -> str:
    declarations = ["  logic [31:0] irq_sources; // One interrupt bit per IP block"]
    instances = []
    mux_cases = []
    pready_mux_cases = []
    irq_terms = []
    for index, block in enumerate(blocks):
        prefix = f"{block}_{index}"
        declarations.append(f"  logic [{data_width - 1}:0] {prefix}_prdata; // Read data from {block}\n  logic        {prefix}_pready; // Ready from {block}\n  logic        {prefix}_pslverr; // Error from {block}\n  logic        {prefix}_irq; // Interrupt request from {block}")
        irq_terms.append(f"{prefix}_irq")
        mux_cases.append(f"      4'h{index:X}: begin prdata_d = {prefix}_prdata; pslverr_d = {prefix}_pslverr; pready_d = {prefix}_pready; end")
        extra_ports = ""
        if block == "mac_array":
            declarations.append(f"  logic [31:0] {prefix}_mac_result; // MAC result from {block}\n  logic        {prefix}_mac_valid; // MAC valid from {block}")
            extra_ports = f",\n    .mac_result_o({prefix}_mac_result),\n    .mac_valid_o({prefix}_mac_valid)"
        instances.append(f"""  {project}_{block}_rtl u_{block} (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .psel_i(psel_i && paddr_i[15:12] == 4'h{index:X}),
    .penable_i(penable_i),
    .pwrite_i(pwrite_i),
    .paddr_i(paddr_i),
    .pwdata_i(pwdata_i),
    .prdata_o({prefix}_prdata),
    .pready_o({prefix}_pready),
    .pslverr_o({prefix}_pslverr),
    .irq_o({prefix}_irq){extra_ports}
  );""")
    # Build irq_sources assignment: pack all IRQ bits into [31:0], zero-pad upper bits
    num_irqs = len(irq_terms)
    pad_bits = 32 - num_irqs
    if pad_bits > 0:
        irq_concat = f"{{{pad_bits}'b0, " + ", ".join(reversed(irq_terms)) + "}"
    else:
        irq_concat = "{" + ", ".join(reversed(irq_terms[:32])) + "}"
    return f"""// GOLDEN_PATTERN: top_irq_mux
module {project}_top (
  input  logic        clk_i,     // Clock input
  input  logic        rst_ni,    // Active-low synchronous reset
  input  logic        psel_i,    // APB slave select
  input  logic        penable_i, // APB access phase indicator
  input  logic        pwrite_i,  // APB write enable
  input  logic [31:0] paddr_i,   // APB byte address
  input  logic [{data_width - 1}:0] pwdata_i,  // APB write data
  output logic [{data_width - 1}:0] prdata_o,  // APB read data
  output logic        pready_o,  // APB ready response
  output logic        pslverr_o, // APB error response
  output logic [31:0] irq_o      // Aggregated interrupt outputs
);
{chr(10).join(declarations)}
  logic [{data_width - 1}:0] prdata_d;
  logic        pslverr_d;
  logic        pready_d;

  assign irq_o = irq_sources;
  assign irq_sources = {irq_concat};

{chr(10).join(instances)}

  // Address-muxed response: only the selected slave's prdata/pslverr/pready drives output
  always_comb begin
    prdata_d = '0;
    pslverr_d = 1'b0;
    pready_d = 1'b1;
    unique case (paddr_i[15:12])
{chr(10).join(mux_cases)}
      default: begin prdata_d = '0; pslverr_d = 1'b1; pready_d = 1'b1; end
    endcase
  end

  assign prdata_o = prdata_d;
  assign pready_o = pready_d;
  assign pslverr_o = pslverr_d;
endmodule
"""


def verify_rtl_files(spec: dict[str, Any], files: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a deterministic self-check report for the Agent 2 prompt rules."""
    blocks = [block["name"] for block in spec["ip_blocks"]]
    by_name = {file["filename"]: file for file in files}
    rtl_text = "\n".join(file["content"] for file in files if file["language"] == "systemverilog")
    checks = {rule: True for rule in QUALITY_RULES}
    failures: list[str] = []

    expected = {f"{block}.sv" for block in blocks} | {f"{block}_pkg.sv" for block in blocks} | {f"{block}_intf.sv" for block in blocks} | {f"{spec['project_name']}_top.sv"}
    missing = sorted(expected - set(by_name))
    if missing:
        checks["module_header"] = False
        failures.append(f"missing files: {missing}")

    for signal in APB_SLAVE_INTERFACE["signals"]:
        if signal["name"] not in rtl_text:
            checks["apb_pinout_locked"] = False
            failures.append(f"missing APB signal {signal['name']}")
    if " reg " in rtl_text or " wire " in rtl_text:
        checks["logic_ports"] = False
        failures.append("reg/wire token found; Agent 2 must use logic")
    for token in FORBIDDEN_RTL_TOKENS:
        if token in rtl_text:
            checks["no_forbidden_rtl_tokens"] = False
            failures.append(f"forbidden RTL token found: {token}")
    required_tokens = {
        "clk_reset_present": ("clk_i", "rst_ni"),
        "always_ff_present": ("always_ff @(posedge clk_i)",),
        "always_comb_present": ("always_comb",),
        "fsm_enum_present": ("typedef enum logic", "state_t"),
        "q_d_pipeline_naming": ("_q", "_d"),
        "outputs_driven": ("assign pready_o", "assign pslverr_o", "prdata_o <="),
        "top_wires_interrupts": ("irq_o", "irq_sources", "assign irq_sources"),
    }
    for rule, tokens in required_tokens.items():
        if not all(token in rtl_text for token in tokens):
            checks[rule] = False
            failures.append(f"{rule} missing one of {tokens}")

    if any(block == "mac_array" for block in blocks) and not all(token in rtl_text for token in ("stage_1_acc_q", "stage_1_acc_d")):
        checks["q_d_pipeline_naming"] = False
        failures.append("mac_array pipeline must expose stage_1_acc_q/stage_1_acc_d")

    if "AGENT2_PATTERN_ID: apb_slave_template" not in rtl_text:
        checks["apb_template_marker_present"] = False
        failures.append("APB pattern reuse marker missing: AGENT2_PATTERN_ID: apb_slave_template")

    top = by_name.get(f"{spec['project_name']}_top.sv", {}).get("content", "")
    for block in blocks:
        if f"u_{block}" not in top or f"{spec['project_name']}_{block}_rtl" not in top:
            checks["top_instantiates_all_blocks"] = False
            failures.append(f"top does not instantiate {block}")
    linter_report = lint_rtl_files(spec, files)
    checks["static_rtl_linter_pass"] = linter_report["pass"]
    if not linter_report["pass"]:
        failures.extend(f"rtl_linter: {finding['message']}" for finding in linter_report["findings"])

    return {
        "agent": "Agent 2 RTL Designer",
        "pass": all(checks.values()),
        "checks": checks,
        "failures": failures,
        "pattern_manifest": pattern_manifest(spec),
        "linter_report": linter_report,
        "file_count": len(files),
        "block_count": len(blocks),
        "generated_files": sorted(by_name),
    }


def _pipeline_critical_path_file(file: dict[str, Any], fix_request: dict[str, Any]) -> dict[str, Any]:
    content = file.get("content", "")
    if "AUTO_PIPELINE_FIX: PIPELINE_CRITICAL_PATH" in content:
        return file
    critical_path = str(fix_request.get("critical_path", "unknown critical path")).replace("*/", "")
    setup_slack = fix_request.get("setup_slack_ns", "unknown")
    patch = f"""
  // AUTO_PIPELINE_FIX: PIPELINE_CRITICAL_PATH
  // Setup Slack < 0 detected by Agent 4 STA; critical path sent back to Agent 2.
  // setup_slack_ns={setup_slack}; critical_path={critical_path}
  logic [DATA_WIDTH-1:0] timing_stage_1_q;
  logic [DATA_WIDTH-1:0] timing_stage_1_d;

  always_comb begin
    timing_stage_1_d = reg0_d;
  end
"""
    patched = content.replace("  always_ff @(posedge clk_i) begin", patch + "\n  always_ff @(posedge clk_i) begin", 1)
    patched = patched.replace("      prdata_o <= RESET_VALUE;", "      prdata_o <= RESET_VALUE;\n      timing_stage_1_q <= RESET_VALUE;", 1)
    patched = patched.replace("      prdata_o <= prdata_d;", "      timing_stage_1_q <= timing_stage_1_d;\n      prdata_o <= timing_stage_1_q;", 1)
    return {**file, "content": patched, "line_count": len(patched.rstrip("\n").splitlines())}


def _debug_report_file(report: dict[str, Any]) -> RTLFile:
    import json

    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    return RTLFile("agent2_debug_report.json", "json", content, len(content.rstrip("\n").splitlines()), [])


def _file(filename: str, content: str, dependencies: list[str]) -> RTLFile:
    return RTLFile(filename, "systemverilog", content, len(content.rstrip("\n").splitlines()), dependencies)
