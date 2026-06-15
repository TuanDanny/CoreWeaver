import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pythonpath_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env

def _skeleton_env() -> dict[str, str]:
    env = _pythonpath_env()
    env["COREWEAVER_RUN_PROFILE"] = "local_skeleton"
    return env


def test_studio_runner_module_skeleton_start() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "coreweaver.studio_runner",
            "start",
            "--run-id",
            "run1",
            "--thread-id",
            "thread1",
            "--output-dir",
            "runs/run1",
            "--project-name",
            "p",
            "--requirement",
            "hello",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=_skeleton_env(),
    )
    assert completed.returncode == 0
    assert "CORE_SKELETON_READY" in completed.stdout


def test_studio_runner_script_start_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["COREWEAVER_RUN_PROFILE"] = "local_skeleton"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "src" / "coreweaver" / "studio_runner.py"),
            "start",
            "--run-id",
            "run-script",
            "--thread-id",
            "thread-script",
            "--output-dir",
            "runs/run-script",
            "--project-name",
            "p",
            "--requirement",
            "hello",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "CORE_SKELETON_READY" in completed.stdout


def test_studio_runner_default_output_dir() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["COREWEAVER_RUN_PROFILE"] = "local_skeleton"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "src" / "coreweaver" / "studio_runner.py"),
            "start",
            "--run-id",
            "run-default-output",
            "--thread-id",
            "thread-default-output",
            "--project-name",
            "p",
            "--requirement",
            "hello",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "CORE_SKELETON_READY" in completed.stdout


def test_studio_runner_default_profile_runs_mock_swarm(tmp_path: Path) -> None:
    env = _pythonpath_env()
    env.pop("COREWEAVER_RUN_PROFILE", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "coreweaver.studio_runner",
            "start",
            "--run-id",
            "run-mock-swarm",
            "--thread-id",
            "thread-mock-swarm",
            "--output-dir",
            str(tmp_path),
            "--project-name",
            "npu",
            "--planning-mode",
            "deep_planning",
            "--requirement",
            "Design a Secure Edge AI Vision NPU with AXI4 DMA, APB CSRs, 64KB SRAM, AES-256 key lock, 500MHz, <2W.",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "agent1_cluster_assignment" in completed.stdout
    assert "PLAN_REVIEW" in completed.stdout
    assert (tmp_path / "reports" / "architecture_plan.md").exists()


def test_studio_runner_imports_without_old_core() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import studio.backend.runner; import studio.backend.agent_service; import studio.backend.trace_replay; import studio.backend.trace_diff; print('ok')",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=_pythonpath_env(),
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_studio_runner_uses_coreweaver_module() -> None:
    from studio.backend.runner import RunnerManager

    manager = RunnerManager()
    command = manager._default_command(
        "start",
        {
            "project_name": "p",
            "run_id": "run1",
            "thread_id": "thread1",
            "output_dir": "runs/run1",
            "checkpoint_db": "runs/checkpoints.sqlite",
            "planning_mode": "normal",
            "requirement": "hello",
            "attachment_context": "runs/run1/inputs/attachment_context.md",
        },
    )
    assert command[:2] == [sys.executable, str(ROOT / "src" / "coreweaver" / "studio_runner.py")]
    assert "--attachment-context" in command


def test_studio_runner_resume_command_preserves_requirement_and_action() -> None:
    from studio.backend.runner import RunnerManager

    manager = RunnerManager()
    manager.state.requirement = "Design an AI chip."
    command = manager._default_command(
        "resume",
        {
            "project_name": "p",
            "run_id": "run1",
            "thread_id": "thread1",
            "output_dir": "runs/run1",
            "resume_action": "REQUIREMENT_CLARIFICATION",
            "notes": "Add AXI/APB, SRAM, reset, clock, and power details.",
        },
    )

    assert "--requirement" in command
    assert command[command.index("--requirement") + 1] == "Design an AI chip."
    assert "--resume-action" in command
    assert command[command.index("--resume-action") + 1] == "REQUIREMENT_CLARIFICATION"


def test_studio_backend_skips_credentials_for_skeleton() -> None:
    from studio.backend.runner import _core_requires_credentials
    from studio.backend.server import _core_runtime_capabilities

    assert _core_requires_credentials() is False
    assert _core_runtime_capabilities()["requiresCredential"] is False
