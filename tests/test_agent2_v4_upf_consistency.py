from semiconductor_swarm.agents.agent2_rtl.phase1_artifacts import build_phase1_artifacts
from semiconductor_swarm.agents.agent2_rtl.semantic import build_rtl_module_index

from tests.agent2_v4_fixture_utils import rtl_fixture_files, v4_fixture_spec


def test_upf_consistency_accepts_golden_power_domain_hierarchy():
    spec = v4_fixture_spec()
    files = rtl_fixture_files("golden_rtl")
    artifacts = build_phase1_artifacts(spec, files, build_rtl_module_index(files), {"requires_real_tools": False, "swarm_mode": "demo", "tools": {}, "blocking_findings": []})

    report = artifacts["upf_consistency_report"]

    assert report["schema_version"] == "agent2.upf_consistency_report.v1"
    assert report["low_power_intent_present"] is True
    assert report["pass"] is True
    assert report["blocking_findings"] == []


def test_upf_consistency_blocks_missing_isolation_and_hierarchy():
    spec = v4_fixture_spec()
    spec["constraints"]["power_intent"]["power_domains"][0].update(
        {"elements": ["missing_block"], "requires_isolation": True, "isolation": None}
    )
    files = rtl_fixture_files("golden_rtl")
    artifacts = build_phase1_artifacts(spec, files, build_rtl_module_index(files), {"requires_real_tools": False, "swarm_mode": "demo", "tools": {}, "blocking_findings": []})

    rules = {finding["rule"] for finding in artifacts["upf_consistency_report"]["blocking_findings"]}

    assert rules == {"upf_hierarchy_missing", "isolation_strategy_missing"}