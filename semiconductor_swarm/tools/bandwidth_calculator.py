"""Deterministic bandwidth tools for Agent 1."""
from __future__ import annotations


def calculate_bandwidth(
    bus_width_bits: int,
    freq_mhz: int,
    efficiency: float = 0.8,
) -> dict[str, float | int]:
    """Calculate peak and effective bandwidth for a synchronous bus."""
    if bus_width_bits <= 0 or freq_mhz < 0:
        raise ValueError("bus_width_bits must be positive and freq_mhz non-negative")
    if not 0 < efficiency <= 1:
        raise ValueError("efficiency must be in the range (0, 1]")

    peak_mb_s = bus_width_bits / 8 * freq_mhz
    effective_mb_s = peak_mb_s * efficiency
    return {
        "bus_width_bits": bus_width_bits,
        "freq_mhz": freq_mhz,
        "efficiency": efficiency,
        "peak_mb_s": round(peak_mb_s, 2),
        "effective_mb_s": round(effective_mb_s, 2),
    }
