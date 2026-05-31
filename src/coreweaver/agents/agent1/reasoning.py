from __future__ import annotations

from .intake import extract_requirement_signals
from .models import ArchitecturePlan, ManagerSummary, RegisterEntry, RequirementPack


class ArchitectureReasoningEngine:
    def synthesize(self, pack: RequirementPack, summaries: tuple[ManagerSummary, ...]) -> ArchitecturePlan:
        signals = extract_requirement_signals(pack.raw_text)
        text = pack.raw_text.lower()
        title = _title_for(pack)
        interfaces = _interface_section(signals)
        registers = _registers(text)
        security = _security_section(text)
        top_blocks = (
            "Firmware/APB control plane",
            "AXI4 DMA/image data plane" if "axi" in text else "Primary data ingress/egress interface",
            "MAC/datapath core" if "mac" in text or "npu" in text else "Compute/control core",
            "SRAM/buffer subsystem" if "sram" in text or "buffer" in text else "Local state/memory block",
            "Security/encryption boundary" if "aes" in text or "secure" in text else "Safety and protection boundary",
        )
        memory_map = (
            "0x0000-0x0FFF: APB CSR window",
            "0x1000-0x1FFF: status/error/interrupt window",
            "0x2000-0x2FFF: protected key/programming control window" if "key" in text or "aes" in text else "0x2000-0x2FFF: implementation-specific control window",
            "SRAM buffer address window is locked in Agent2 handoff after bus integration sizing.",
        )
        provenance = tuple(f"{summary.manager_id}:{summary.output_hash[:12]}" for summary in summaries)
        return ArchitecturePlan(
            title=title,
            requirement_summary=pack.raw_text,
            assumptions=pack.assumptions or ("Implementation details not specified are held as explicit open assumptions.",),
            open_questions=pack.missing_fields,
            top_level_blocks=top_blocks,
            interfaces=interfaces,
            memory_map=memory_map,
            registers=registers,
            security_model=security,
            datapath_control=_datapath_section(text),
            reset_clock_cdc=_clock_reset_section(signals),
            interrupt_error_policy=(
                "APB-visible sticky error/status registers use W1C where firmware clears events.",
                "DMA, AES, SRAM ECC/parity, and protocol errors must map to explicit interrupt/status bits.",
            ),
            formal_intent=(
                "Prove APB register access policy, including write-only/no-readback fields.",
                "Prove lock-after-boot monotonicity and no write after lock for protected controls.",
                "Prove AXI/APB handshake stability and no invalid ready/valid response.",
            ),
            dv_intent=(
                "cocotb APB CSR regressions for access type, reset, W1C, WO, and lock behavior.",
                "AXI DMA stress with backpressure, burst edges, reset injection, and malformed transactions.",
                "Security negative tests for readback, debug visibility, and post-lock key writes.",
            ),
            ppa_risks=_ppa_section(signals, text),
            agent2_handoff_contract=(
                "Agent2 receives locked interface widths, CSR access policy, reset/clock assumptions, and signoff findings.",
                "Agent2 may not rename externally visible interfaces without handoff contract update.",
            ),
            provenance_refs=provenance,
        )


def _title_for(pack: RequirementPack) -> str:
    text = pack.raw_text.lower()
    if "npu" in text:
        return "Secure Edge AI Vision NPU Architecture Plan"
    if "cpu" in text:
        return "CPU Architecture Plan"
    if "uart" in text:
        return "UART Peripheral Architecture Plan"
    if "i2c" in text:
        return "I2C Peripheral Architecture Plan"
    return f"{pack.project_name} Architecture Plan"


def _interface_section(signals: dict[str, object]) -> tuple[str, ...]:
    interfaces = tuple(signals.get("interfaces") or ())
    items: list[str] = []
    if "AXI4" in interfaces or "AXI" in interfaces:
        items.append("AXI4 data-plane interface for high-throughput DMA and image/weight movement.")
    if "APB" in interfaces:
        items.append("APB configuration interface for firmware-visible CSRs.")
    if not items:
        items.append("Interface contract is open; bus width and protocol must be clarified before Agent2.")
    return tuple(items)


def _registers(text: str) -> tuple[RegisterEntry, ...]:
    registers = [
        RegisterEntry(name="CTRL", offset="0x0000", access="RW", reset="0x0", description="Enable, soft reset request, operating mode."),
        RegisterEntry(name="STATUS", offset="0x0004", access="RO", reset="0x0", description="Busy, idle, done, and fault summary."),
        RegisterEntry(name="IRQ_STATUS", offset="0x0008", access="W1C", reset="0x0", description="Sticky interrupt causes, cleared by writing 1."),
        RegisterEntry(name="IRQ_ENABLE", offset="0x000C", access="RW", reset="0x0", description="Interrupt enables."),
    ]
    if "key" in text or "aes" in text:
        registers.extend(
            [
                RegisterEntry(name="AES_KEY_WDATA", offset="0x0100", access="WO", reset="X", description="AES-256 key programming window; no readback under any circumstance."),
                RegisterEntry(name="AES_KEY_LOCK", offset="0x0120", access="WO", reset="0x0", description="Set-only lock-after-boot control; once set, key writes are ignored until reset policy permits re-provisioning."),
                RegisterEntry(name="AES_KEY_STATUS", offset="0x0124", access="RO", reset="0x0", description="Reports locked/programmed state without exposing key material."),
            ]
        )
    return tuple(registers)


def _security_section(text: str) -> tuple[str, ...]:
    if "key" in text or "aes" in text or "secure" in text:
        return (
            "AES-256 decrypt runs on the weight fetch path before MAC-array use.",
            "Secret key programming is software-writable but hardware-protected as WO, lock-after-boot, no readback.",
            "Debug, trace, scan-visible artifacts, and APB reads must never expose key material.",
        )
    return ("No explicit security mechanism requested; keep debug/trace secret-scan active.",)


def _datapath_section(text: str) -> tuple[str, ...]:
    if "npu" in text or "mac" in text:
        return (
            "DMA fills SRAM/image buffers while MAC array consumes tiled data.",
            "Encrypted weights pass through AES decrypt before entering the MAC-array feed path.",
            "Control path arbitrates DMA, SRAM banking, AES readiness, and MAC scheduling.",
        )
    return ("Datapath/control split remains lightweight until workload details are provided.",)


def _clock_reset_section(signals: dict[str, object]) -> tuple[str, ...]:
    clock = str(signals.get("clock") or "TBD")
    return (
        f"Target clock: {clock}.",
        "Reset polarity, reset synchronizers, and cross-domain paths must be locked before RTL.",
        "CDC/RDC review required for APB control to high-speed datapath crossings.",
    )


def _ppa_section(signals: dict[str, object], text: str) -> tuple[str, ...]:
    risks = []
    if str(signals.get("clock") or "") == "500MHz":
        risks.append("500MHz timing is a high-risk target for AES + SRAM + MAC feed without deliberate pipelining.")
    if "power_budget" in signals:
        risks.append(f"Power budget {signals['power_budget']} needs workload, process, voltage, and activity assumptions before pass/fail.")
    if not risks:
        risks.append("PPA cannot be quantified until process node, voltage, activity, and floorplan assumptions are known.")
    return tuple(risks)
