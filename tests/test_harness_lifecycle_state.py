import json
from pathlib import Path

from coreweaver.harness.persistent_state import validate_feature_list


ROOT = Path(__file__).resolve().parents[1]


def test_feature_list_tracks_true_swarm_features() -> None:
    data = json.loads((ROOT / "feature_list.json").read_text(encoding="utf-8"))
    assert data["version"] == "1.1.0"
    feature_ids = {feature["id"] for feature in data["features"]}
    assert "agent1.true_swarm.mock_profile" in feature_ids
    assert "agent1.signoff_handoff" in feature_ids


def test_feature_list_matches_schema() -> None:
    result = validate_feature_list(ROOT)
    assert result.passed, result.errors


def test_feature_list_schema_rejects_drift(tmp_path: Path) -> None:
    (tmp_path / "feature_list.schema.json").write_text(
        (ROOT / "feature_list.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "feature_list.json").write_text(
        json.dumps(
            {
                "version": "1.1.0",
                "features": [
                    {
                        "id": "agent1.example",
                        "status": "implemented",
                        "summary": "legacy shape",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_feature_list(tmp_path)

    assert not result.passed
    assert any("title" in error for error in result.errors)
    assert any("status" in error for error in result.errors)
    assert any("summary" in error for error in result.errors)


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


def test_ci_and_finish_workflow_run_benchmarks() -> None:
    workflow = (ROOT / ".github" / "workflows" / "harness.yml").read_text(encoding="utf-8")
    finish = (ROOT / "scripts" / "finish_codex_task.ps1").read_text(encoding="utf-8")
    assert "scripts\\run_benchmarks.py" in workflow
    assert "scripts\\run_benchmarks.py" in finish
    assert "--results" in workflow
    assert "--results" in finish


def test_finish_workflow_blocks_untracked_mirror_and_scratch_files() -> None:
    finish = (ROOT / "scripts" / "finish_codex_task.ps1").read_text(encoding="utf-8")
    assert "blockedUntrackedPrefixes" in finish
    assert "src/coreweaver/agents/agents/" in finish
    assert "src/coreweaver/agents/harness/" in finish
    assert "src/coreweaver/agents/runtime/" in finish
    assert "src/coreweaver/agents/api.py" in finish
    assert "kiemtra*.txt" in finish
    assert "git add -A" in finish
