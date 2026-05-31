from pathlib import Path

from coreweaver.harness.rules import load_rules

ROOT = Path(__file__).resolve().parents[1]


def test_packaging_boundary_rule_exists() -> None:
    rules = {rule.id: rule for rule in load_rules(ROOT / ".rules")}
    rule = rules["packaging.package_boundary"]
    assert rule.severity.value == "error"
    assert rule.applies_to == "packaging"
    assert "package" in rule.description.lower()


def test_src_layout_rule_exists() -> None:
    rules = {rule.id: rule for rule in load_rules(ROOT / ".rules")}
    rule = rules["architecture.src_layout"]
    assert rule.severity.value == "error"
    assert rule.applies_to == "architecture"
    assert "src" in rule.description.lower()


def test_package_first_adr_exists() -> None:
    adr = ROOT / "docs" / "adr" / "0001-package-first-core.md"
    text = adr.read_text(encoding="utf-8")
    assert "Package-First Core" in text
    assert ".rules/" in text
    assert "AGENTS.md" in text
