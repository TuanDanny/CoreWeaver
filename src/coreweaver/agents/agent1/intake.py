from __future__ import annotations

import re

from coreweaver.framework_types import stable_hash

from .models import ClarificationQuestion, RequirementClassification, RequirementPack

_DESIGN_WORDS = {
    "apb",
    "axi",
    "ahb",
    "asic",
    "chip",
    "clock",
    "cpu",
    "csr",
    "dma",
    "fpga",
    "i2c",
    "interface",
    "irq",
    "memory",
    "npu",
    "register",
    "reset",
    "rtl",
    "soc",
    "sram",
    "uart",
}

_CASUAL_PATTERNS = (
    "ban la ai",
    "bạn là ai",
    "may tuoi",
    "mấy tuổi",
    "hello",
    "hi",
    "xin chao",
    "xin chào",
)


def classify_requirement(text: str) -> RequirementClassification:
    normalized = _normalize(text)
    if not normalized:
        return RequirementClassification.AMBIGUOUS_CHIP_IDEA
    if any(pattern in normalized for pattern in _CASUAL_PATTERNS) and not any(word in normalized for word in _DESIGN_WORDS):
        return RequirementClassification.NON_DESIGN_CONVERSATION
    if not any(word in normalized for word in _DESIGN_WORDS):
        return RequirementClassification.NON_DESIGN_CONVERSATION
    missing = missing_requirement_fields(text)
    if len(missing) >= 3:
        return RequirementClassification.AMBIGUOUS_CHIP_IDEA
    return RequirementClassification.DESIGN_READY_REQUIREMENT


def build_requirement_pack(*, requirement: str, project_name: str, planning_mode: str, attachment_refs: tuple[str, ...] = ()) -> RequirementPack:
    classification = classify_requirement(requirement)
    extracted = extract_requirement_signals(requirement)
    missing = missing_requirement_fields(requirement)
    assumptions: list[str] = []
    if "reset" not in extracted:
        assumptions.append("Reset polarity and reset domain remain to be confirmed before RTL.")
    if "clock" not in extracted:
        assumptions.append("Clocking plan remains to be confirmed before timing signoff.")
    return RequirementPack(
        requirement_id=f"req:{stable_hash(requirement)[:16]}",
        raw_text=requirement,
        project_name=project_name,
        planning_mode=planning_mode,
        classification=classification,
        extracted=extracted,
        missing_fields=tuple(missing),
        assumptions=tuple(assumptions),
        attachment_refs=attachment_refs,
    )


def build_clarification(pack: RequirementPack) -> ClarificationQuestion:
    fields = pack.missing_fields or ("interface", "clock/reset", "memory map")
    return ClarificationQuestion(
        question_id=f"clar:{stable_hash([pack.requirement_id, fields])[:16]}",
        missing_fields=tuple(fields),
        question="Please clarify: " + "; ".join(fields) + ".",
        reason="Agent1 needs these fields before a release-ready architecture contract can be produced.",
    )


def extract_requirement_signals(text: str) -> dict[str, object]:
    normalized = _normalize(text)
    signals: dict[str, object] = {}
    interfaces: list[str] = []
    for bus in ("axi4", "axi", "apb", "ahb", "uart", "i2c", "spi"):
        if bus in normalized:
            interfaces.append(bus.upper())
    if interfaces:
        signals["interfaces"] = tuple(sorted(set(interfaces)))
    width_matches = re.findall(r"(\d+)\s*-\s*bit|\b(\d+)\s*bit", normalized)
    widths = sorted({int(a or b) for a, b in width_matches if a or b})
    if widths:
        signals["widths"] = tuple(widths)
    mem = re.findall(r"(\d+)\s*(kb|mb)\s*(sram|buffer|memory)?", normalized)
    if mem:
        signals["memory"] = tuple(" ".join(part for part in match if part).upper() for match in mem)
    freq = re.findall(r"(\d+)\s*mhz", normalized)
    if freq:
        signals["clock"] = f"{freq[0]}MHz"
    power = re.findall(r"<\s*(\d+(?:\.\d+)?)\s*w|under\s*(\d+(?:\.\d+)?)\s*w", normalized)
    if power:
        value = next((a or b for a, b in power if a or b), "")
        signals["power_budget"] = f"< {value}W"
    if "aes" in normalized or "decrypt" in normalized or "secure" in normalized:
        signals["security"] = "secure crypto/key policy required"
    if "reset" in normalized:
        signals["reset"] = "mentioned"
    if "irq" in normalized or "interrupt" in normalized:
        signals["interrupt"] = "mentioned"
    return signals


def missing_requirement_fields(text: str) -> tuple[str, ...]:
    signals = extract_requirement_signals(text)
    missing: list[str] = []
    if "interfaces" not in signals:
        missing.append("bus/interface contract")
    if "clock" not in signals:
        missing.append("target clock/frequency")
    normalized = _normalize(text)
    if "memory" not in signals and not any(token in normalized for token in ("register", "csr", "csrs")):
        missing.append("memory/register map")
    if "security" not in signals and any(word in _normalize(text) for word in ("secure", "key", "crypto", "aes")):
        missing.append("security/key protection policy")
    if "reset" not in signals:
        missing.append("reset policy")
    return tuple(missing)


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())
