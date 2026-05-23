from semiconductor_swarm.tools.tool_detection import detect_real_tools


def test_detect_real_tools_schema():
    report = detect_real_tools()
    assert set(report) == {"tools", "groups"}
    for name in ("sby", "yosys", "z3", "verilator", "make", "quartus_sh", "cocotb"):
        assert name in report["tools"]
        assert "available" in report["tools"][name]
    for group in ("formal", "dv", "quartus"):
        assert group in report["groups"]
        assert "available" in report["groups"][group]
        assert "missing" in report["groups"][group]