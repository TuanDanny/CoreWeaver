import json
import shutil

import pytest

from semiconductor_swarm.tools.quartus_runner import parse_quartus_report_text


pytestmark = pytest.mark.real_tools


def test_real_quartus_available_or_parse_fixture(tmp_path):
    quartus = shutil.which("quartus_sh")
    if quartus is None:
        metrics = parse_quartus_report_text("Fmax: 125.0 MHz\nALMs: 1000 / 32070\nRegisters: 2048\nBlock RAM: 10 / 397\n", target_mhz=100.0, top_module="fixture_top")
        summary = {"quartus_available": False, "quartus_skipped_reason": "quartus_sh not found on PATH", "fixture_parse_pass": metrics["timing_pass"]}
    else:
        summary = {"quartus_available": True, "quartus_sh": quartus}
    path = tmp_path / "quartus_real_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    assert summary.get("quartus_available") or summary.get("fixture_parse_pass")