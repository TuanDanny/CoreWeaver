import json

from semiconductor_swarm.agents.agent2_rtl.orchestrator import _repair_lec_result, _repair_patch_records
from semiconductor_swarm.agents.agent2_rtl.rtl_designer import generate_rtl_files
from semiconductor_swarm.agents.agent1_planning.architect import generate_architecture_spec


def test_repair_patch_records_and_lec_proxy_capture_logic_affecting_changes():
    patches = _repair_patch_records(1, {"a.sv": "old"}, {"a.sv": "new", "b.sv": "same"})
    lec = _repair_lec_result(patches)

    assert patches == [{"patch_id": "repair-1-01", "file": "a.sv", "pre_sha256": "old", "post_sha256": "new", "change_type": "content_update", "scope": "minimal_local_rtl_repair", "logic_affecting": True, "requires_lec": True}, {"patch_id": "repair-1-02", "file": "b.sv", "pre_sha256": None, "post_sha256": "same", "change_type": "content_update", "scope": "minimal_local_rtl_repair", "logic_affecting": True, "requires_lec": True}]
    assert lec["required"] is True
    assert lec["tool"] == "yosys"
    assert "equiv_status -assert" in lec["command"]


def test_generated_debug_lec_artifact_is_present_and_schema_stable():
    spec = generate_architecture_spec("IoT AI camera chip <1W 100MHz", "iot_camera")
    files = generate_rtl_files(spec, debug=True)
    lec = json.loads(next(file for file in files if file["filename"] == "lec_equivalence_report.json")["content"])

    assert lec["schema_version"] == "agent2.lec_equivalence_report.v1"
    assert lec["tool"] == "yosys"
    assert lec["pass"] is True