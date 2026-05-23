import json
import shutil

import pytest

from semiconductor_swarm.tools.symbiyosys_runner import parse_sby_result_text


pytestmark = pytest.mark.real_tools


def test_real_formal_tools_available_or_skip(tmp_path):
    missing = [tool for tool in ("sby", "yosys", "z3") if shutil.which(tool) is None]
    if missing:
        pytest.skip(f"formal real tools missing: {missing}")
    summary = {"formal_tools_available": True, "tools": {tool: shutil.which(tool) for tool in ("sby", "yosys", "z3")}}
    path = tmp_path / "formal_real_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")
    assert summary["formal_tools_available"]


def test_parse_sby_pass_fixture():
    result = parse_sby_result_text("SBY 19:00:00 engine_0: smtbmc z3\nStatus: PASSED\n", "timer")
    assert result["pass"] is True
    assert result["status"] == "PASS"