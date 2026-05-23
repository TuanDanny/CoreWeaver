import json

from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files


def _artifact_map(files: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {file["filename"]: json.loads(file["content"]) for file in files if str(file["filename"]).endswith(".json")}


def test_agent2_v4_toolchain_reproducibility_fingerprints_are_stable():
    spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
    first = _artifact_map(generate_rtl_files(spec, debug=True))
    second = _artifact_map(generate_rtl_files(spec, debug=True))

    assert first["rtl_generation_fingerprint.json"]["schema_version"] == "agent2.rtl_generation_fingerprint.v1"
    assert first["toolchain_reproducibility_report.json"]["schema_version"] == "agent2.toolchain_reproducibility_report.v1"
    assert first["rtl_generation_fingerprint.json"]["content_hash"] == second["rtl_generation_fingerprint.json"]["content_hash"]
    assert first["rtl_generation_fingerprint.json"]["compile_order_hash"] == second["rtl_generation_fingerprint.json"]["compile_order_hash"]
    assert first["toolchain_reproducibility_report.json"]["pass"] is True
    assert first["tool_provenance.json"]["schema_version"] == "agent2.tool_provenance.v1"
    assert set(first["tool_provenance.json"]["tools"]) == {"verilator", "yosys", "symbiyosys"}