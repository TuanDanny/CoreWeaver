from __future__ import annotations

from pathlib import Path


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


def rtl_fixture_files(folder: str) -> list[dict[str, object]]:
    files = []
    for path in sorted((FIXTURE_ROOT / folder).glob("*.sv")):
        content = path.read_text()
        files.append(
            {
                "filename": path.name,
                "language": "systemverilog",
                "content": content,
                "line_count": len(content.rstrip("\n").splitlines()),
                "dependencies": [],
            }
        )
    return files


def v4_fixture_spec() -> dict[str, object]:
    return {
        "project_name": "agent2_v4_fixture",
        "ip_blocks": [
            {"name": "interrupt_ctrl"},
            {"name": "sram_controller"},
            {"name": "timer"},
        ],
        "interfaces": {"apb_slave": True},
        "constraints": {
            "swarm_mode": "demo",
            "power_intent": {
                "power_domains": [
                    {
                        "name": "CORE",
                        "elements": ["interrupt_ctrl", "sram_controller", "timer"],
                        "requires_isolation": False,
                        "requires_retention": False,
                    }
                ]
            },
        },
        "clocks": [{"name": "clk_i", "domain": "core"}],
        "reset_domains": [{"name": "rst_ni", "domain": "core", "active_low": True}],
    }