import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_feature_list_tracks_true_swarm_features() -> None:
    data = json.loads((ROOT / "feature_list.json").read_text(encoding="utf-8"))
    assert data["version"] == "1.1.0"
    feature_ids = {feature["id"] for feature in data["features"]}
    assert "agent1.true_swarm.mock_profile" in feature_ids
    assert "agent1.signoff_handoff" in feature_ids


def test_lifecycle_files_exist_and_reference_checks() -> None:
    for name in ("progress.md", "session-handoff.md", "init.sh", "init.ps1"):
        assert (ROOT / name).exists()
    handoff = (ROOT / "session-handoff.md").read_text(encoding="utf-8")
    assert "harness_check.py" in handoff
    assert "run_benchmarks.py" in handoff


def test_agents_points_to_state_and_lifecycle_files() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "feature_list.json" in text
    assert "progress.md" in text
    assert "session-handoff.md" in text
