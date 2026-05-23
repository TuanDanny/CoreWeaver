"""Golden Micro-Pattern Library for Agent 2 RTL generation.

Patterns here are deterministic, synthesizable snippets used as source of
truth before Agent 2 emits any RTL.  They deliberately stay small so tests can
prove Agent 2 is pattern-first instead of free-form RTL-first.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GoldenPattern:
    name: str
    category: str
    description: str
    required_tokens: tuple[str, ...]
    forbidden_tokens: tuple[str, ...]
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "required_tokens": list(self.required_tokens),
            "forbidden_tokens": list(self.forbidden_tokens),
            "snippet": self.snippet,
        }


PATTERN_LIBRARY: dict[str, GoldenPattern] = {
    "apb_slave_template": GoldenPattern(
        name="apb_slave_template",
        category="bus_protocol",
        description="APB3 single-cycle ready register slave template from patterns/apb_slave_template.sv.",
        required_tokens=("AGENT2_PATTERN_ID: apb_slave_template", "psel_i", "penable_i", "pwrite_i", "paddr_i", "pwdata_i", "prdata_o", "pready_o", "pslverr_o"),
        forbidden_tokens=("paddr_o", "apb_addr_i", "$display", "initial begin", "#delay"),
        snippet="",
    ),
    "sync_fifo_template": GoldenPattern(
        name="sync_fifo_template",
        category="buffering",
        description="Synchronous FIFO template from patterns/sync_fifo_template.sv.",
        required_tokens=("AGENT2_PATTERN_ID: sync_fifo_template", "always_ff", "always_comb", "wr_ptr_q", "rd_ptr_q", "full_o", "empty_o"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "sync_fifo_verified": GoldenPattern(
        name="sync_fifo_verified",
        category="buffering",
        description="Verified synchronous FIFO from patterns/sync_fifo_verified.sv.",
        required_tokens=("AGENT2_PATTERN_ID: sync_fifo_verified", "always_ff", "always_comb", "wr_ptr_q", "rd_ptr_q", "full_o", "empty_o"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "interrupt_controller_w1c_sticky": GoldenPattern(
        name="interrupt_controller_w1c_sticky",
        category="interrupt",
        description="Sticky W1C interrupt controller from patterns/interrupt_controller_w1c_sticky.sv.",
        required_tokens=("AGENT2_PATTERN_ID: interrupt_controller_w1c_sticky", "always_ff", "always_comb", "sticky_q", "irq_w1c_i", "irq_o"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "apb_timer_counter": GoldenPattern(
        name="apb_timer_counter",
        category="timer",
        description="APB timer/counter with compare IRQ from patterns/apb_timer_counter.sv.",
        required_tokens=("AGENT2_PATTERN_ID: apb_timer_counter", "always_ff", "always_comb", "psel_i", "penable_i", "pready_o", "pslverr_o"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "sram_controller_latency_ready": GoldenPattern(
        name="sram_controller_latency_ready",
        category="memory",
        description="SRAM request/ready controller from patterns/sram_controller_latency_ready.sv.",
        required_tokens=("AGENT2_PATTERN_ID: sram_controller_latency_ready", "always_ff", "always_comb", "ready_o", "rdata_o", "mem_q"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "secded_39_32_encoder_decoder": GoldenPattern(
        name="secded_39_32_encoder_decoder",
        category="reliability",
        description="SECDED 39/32 encoder-decoder from patterns/secded_39_32_encoder_decoder.sv.",
        required_tokens=("AGENT2_PATTERN_ID: secded_39_32_encoder_decoder", "always_ff", "always_comb", "syndrome_o", "correctable_error_o", "uncorrectable_error_o"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "simple_apb_crossbar_1m_ns": GoldenPattern(
        name="simple_apb_crossbar_1m_ns",
        category="bus_protocol",
        description="Simple APB 1-master N-slave crossbar from patterns/simple_apb_crossbar_1m_ns.sv.",
        required_tokens=("AGENT2_PATTERN_ID: simple_apb_crossbar_1m_ns", "always_ff", "always_comb", "slave_psel_o", "pslverr_o", "decode_hit"),
        forbidden_tokens=("$display", "initial begin", "#delay"),
        snippet="",
    ),
    "apb_register_slave": GoldenPattern(
        name="apb_register_slave",
        category="bus_protocol",
        description="APB3 single-cycle ready register slave with q/d state and registered read data.",
        required_tokens=("psel_i", "penable_i", "pwrite_i", "paddr_i", "pwdata_i", "prdata_o", "pready_o", "pslverr_o"),
        forbidden_tokens=("paddr_o", "apb_addr_i", "$display", "initial begin", "#delay"),
        snippet="""// GOLDEN_PATTERN: apb_register_slave
// APB3 setup/access timing: setup when psel_i && !penable_i, access when psel_i && penable_i.
// Outputs are driven on all paths; pready_o is constant-ready for this safe micro-pattern.
""",
    ),
    "q_d_ff_pipeline": GoldenPattern(
        name="q_d_ff_pipeline",
        category="sequential_logic",
        description="q/d flip-flop style with synchronous active-low reset check and no inferred latch.",
        required_tokens=("always_comb", "always_ff @(posedge clk_i)", "_q", "_d"),
        forbidden_tokens=("always_latch", " reg ", " wire "),
        snippet="""// GOLDEN_PATTERN: q_d_ff_pipeline
// Every state-holding signal has _q and _d names; _d gets default in always_comb.
// Every _q register has explicit reset assignment in always_ff.
""",
    ),
    "fsm_enum": GoldenPattern(
        name="fsm_enum",
        category="control_logic",
        description="Enumerated FSM state type for readable synthesis and formal checks.",
        required_tokens=("typedef enum logic", "state_t", "S_IDLE", "S_SETUP", "S_ACCESS"),
        forbidden_tokens=("parameter S_IDLE", "localparam S_IDLE"),
        snippet="""// GOLDEN_PATTERN: fsm_enum
// FSM states use typedef enum logic and state_q/state_d handoff.
""",
    ),
    "top_irq_mux": GoldenPattern(
        name="top_irq_mux",
        category="integration",
        description="Top wrapper instantiates every IP and packs per-block irq into irq_sources.",
        required_tokens=("irq_o", "irq_sources", "assign irq_sources"),
        forbidden_tokens=("assign irq_o = '0; // TODO",),
        snippet="""// GOLDEN_PATTERN: top_irq_mux
// Top-level response mux selects prdata/pslverr/pready by paddr_i[15:12].
// irq_sources packs each child irq with zero padding to 32 bits.
""",
    ),
}


def get_pattern(name: str) -> GoldenPattern:
    try:
        return PATTERN_LIBRARY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown Agent 2 golden pattern: {name}") from exc


def select_patterns_for_spec(spec: dict[str, Any]) -> list[GoldenPattern]:
    """Return deterministic pattern set for any Agent 1 architecture spec."""
    names = ["apb_slave_template", "q_d_ff_pipeline", "fsm_enum", "top_irq_mux"]
    text = " ".join([str(spec.get("project_name", "")), *(str(block.get("name", "")) for block in spec.get("ip_blocks", []))]).lower()
    if any(token in text for token in ("fifo", "cdc", "buffer", "stream")):
        names.extend(["sync_fifo_template", "sync_fifo_verified"])
    if spec.get("constraints", {}).get("agent2_v36_patterns_required"):
        names.extend([
            "interrupt_controller_w1c_sticky",
            "apb_timer_counter",
            "sram_controller_latency_ready",
            "secded_39_32_encoder_decoder",
            "simple_apb_crossbar_1m_ns",
        ])
    return [get_pattern(name) for name in dict.fromkeys(names)]


def pattern_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    patterns = select_patterns_for_spec(spec)
    return {
        "source": "Agent 2 Golden Micro-Pattern Library",
        "manifest_path": "patterns/pattern_manifest.yaml",
        "pattern_count": len(patterns),
        "patterns": [pattern.as_dict() for pattern in patterns],
    }


def repo_patterns_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "patterns"
