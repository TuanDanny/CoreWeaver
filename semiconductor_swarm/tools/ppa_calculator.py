"""Deterministic PPA estimation tools for Agent 1."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TechNode:
    vdd: float
    cap_ff_per_gate: float
    leak_uw_per_mm2: float
    gate_density_per_mm2: int
    sram_mm2_per_kb: float


TECH_DB: dict[str, TechNode] = {
    "28nm": TechNode(0.9, 1.2, 50, 1_500_000, 0.002),
    "12nm": TechNode(0.75, 0.7, 120, 8_000_000, 0.0008),
}


def calculate_ppa(
    tech_node: str,
    logic_gates: int,
    sram_kb: int,
    mac_units: int,
    freq_mhz: int,
) -> dict[str, float | str]:
    """Calculate PPA from lookup tables and simple physical formulas."""
    if tech_node not in TECH_DB:
        raise ValueError(f"Unsupported tech_node: {tech_node}")
    if min(logic_gates, sram_kb, mac_units, freq_mhz) < 0:
        raise ValueError("PPA inputs must be non-negative")

    t = TECH_DB[tech_node]
    alpha = 0.15
    c_total = logic_gates * t.cap_ff_per_gate * 1e-15
    p_dynamic_w = alpha * c_total * (t.vdd**2) * (freq_mhz * 1e6)
    area_logic_mm2 = logic_gates / t.gate_density_per_mm2
    area_sram_mm2 = sram_kb * t.sram_mm2_per_kb
    area_total = (area_logic_mm2 + area_sram_mm2) * 1.3
    tops = mac_units * 2 * freq_mhz / 1e6 if mac_units else 0

    return {
        "power_mw": round(p_dynamic_w * 1000 * 1.2, 2),
        "area_mm2": round(area_total, 3),
        "performance_tops": round(tops, 4),
        "tech_node": tech_node,
    }
