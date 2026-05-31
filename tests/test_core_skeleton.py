from pathlib import Path

from coreweaver.api import CoreRequest, CoreWeaverRuntime
from coreweaver.artifacts import RunLayout
from coreweaver.config import default_config
from coreweaver.errors import ErrorCategory
from coreweaver.mock_llm import MockLlmClient
from coreweaver.registry import Registry
from coreweaver.studio_adapter import CoreWeaverStudioAdapter


def test_core_runtime_boundary_is_skeleton_only() -> None:
    runtime = CoreWeaverRuntime()
    response = runtime.start(CoreRequest(requirement="", project="p", mode="normal"))
    assert response.status == "paused"
    assert runtime.capabilities()["runtimeKind"] == "skeleton"
    assert runtime.capabilities()["requiresCredential"] is False


def test_core_runtime_mock_swarm_runs_agent1(tmp_path: Path) -> None:
    runtime = CoreWeaverRuntime("mock_swarm")
    response = runtime.start(
        CoreRequest(
            requirement="Design an APB timer peripheral with 32-bit CSRs, interrupt status W1C, 100MHz clock, synchronous reset.",
            project="timer",
            mode="normal",
            run_id="api-mock",
            output_dir=str(tmp_path),
        )
    )
    assert response.status == "paused"
    assert response.action_required == "PLAN_REVIEW"
    assert response.run_id == "api-mock"
    assert any(path.endswith("architecture_plan.md") for path in response.artifact_paths)


def test_default_config_points_to_runs() -> None:
    assert default_config().output_root == Path("runs")


def test_run_layout_directories_are_declared(tmp_path: Path) -> None:
    layout = RunLayout(root=tmp_path, run_id="run1")
    assert [path.name for path in layout.directories()] == [
        "input",
        "trace",
        "issues",
        "blackboard",
        "artifacts",
        "signoff",
        "replay",
    ]


def test_registry_rejects_duplicates() -> None:
    registry = Registry[int]()
    registry.register("x", 1)
    try:
        registry.register("x", 2)
    except ValueError as exc:
        assert "duplicate registry entry" in str(exc)
    else:
        raise AssertionError("duplicate registry entry should fail")


def test_mock_llm_is_deterministic() -> None:
    client = MockLlmClient("ok")
    assert client.complete("hello").text == "ok"
    assert client.complete("world").call_id == "mock-2"


def test_error_taxonomy_exists() -> None:
    assert ErrorCategory.SECURITY.value == "SECURITY"

def test_studio_adapter_calls_public_core_boundary() -> None:
    response = CoreWeaverStudioAdapter().start(
        {"requirement": "hello", "project_name": "p", "planning_mode": "normal"}
    )
    assert response.status == "ready"
