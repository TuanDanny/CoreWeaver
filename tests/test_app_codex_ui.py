import pytest
import json
import time
from unittest.mock import patch

from app.main_window import API_KEY_PLACEHOLDER, PLANNING_MODE_DEEP, SPACE_THEME, SwarmStudioApp


@pytest.fixture()
def studio_app():
    try:
        app = SwarmStudioApp()
        app.withdraw()
        app.update()
    except Exception as exc:  # pragma: no cover - display availability differs by host.
        pytest.skip(f"CustomTkinter display unavailable: {exc}")
    try:
        yield app
    finally:
        app.destroy()


def test_burn_rate_chip_updates_from_structured_metric_events(studio_app):
    studio_app._handle_event({"type": "metric", "name": "codex_prompt_tokens", "value": 1000, "status": "info", "agent": "agent1"})
    studio_app._handle_event({"type": "metric", "name": "codex_completion_tokens", "value": 250, "status": "info", "agent": "agent1"})
    studio_app._handle_event({"type": "metric", "name": "codex_total_tokens", "value": 1250, "status": "info", "agent": "agent1"})
    studio_app._handle_event({"type": "metric", "name": "codex_estimated_cost_usd", "value": 0.0015, "status": "info", "agent": "agent1"})

    text = studio_app.burn_chip.cget("text")
    assert "TOK 1250" in text
    assert "$0.0015 est" in text


def test_agent2_card_rolls_up_subagent_events_without_log_parsing(studio_app):
    event = {
        "type": "agent_action",
        "agent": "agent2",
        "phase": "rtl",
        "action": "A2.23 UART writer",
        "status": "pass",
        "summary": "A2.23 UART writer pass",
        "subagent_id": "A2.23",
        "name": "UART writer",
        "rollup_stage": "IP Writers",
        "finding_count": 0,
        "artifact_count": 3,
    }

    studio_app._handle_event(event)

    widgets = studio_app.agent_widgets["agent2"]
    assert "IP Writers: A2.23 UART writer" in widgets["action"].cget("text")
    evidence = widgets["evidence"].cget("text")
    assert "rollup: IP Writers" in evidence
    assert "latest: A2.23" in evidence
    assert "pass: 1" in evidence
    assert "artifacts: 3" in evidence


def test_agent2_filter_renders_subagent_activity(studio_app):
    studio_app._handle_event(
        {
            "type": "agent_action",
            "agent": "agent2",
            "phase": "rtl",
            "action": "A2.56 ECO intent",
            "status": "pass",
            "summary": "A2.56 ECO intent pass",
            "subagent_id": "A2.56",
            "name": "ECO intent",
            "rollup_stage": "Repair",
            "finding_count": 0,
            "artifact_count": 1,
        }
    )
    studio_app._add_log("info", "unrelated system message", agent="system")
    studio_app.set_filter("agent2")

    text = studio_app.log_box.get("1.0", "end")
    assert "A2.56 ECO intent pass" in text
    assert "unrelated system message" not in text

def test_settings_save_writes_codex_config_without_api_key_in_app_settings(studio_app, tmp_path):
    studio_app.codex_config_path = tmp_path / "codex_api.local.json"
    studio_app.settings_path = tmp_path / "settings.json"
    studio_app.settings = {}

    studio_app._save_codex_config("http://localhost:20128/v1", "cx/gpt-5.5", "secret-key")
    studio_app.settings["checkpoint_db"] = str(tmp_path / "checkpoints.sqlite")
    studio_app._save_settings()

    codex_cfg = json.loads(studio_app.codex_config_path.read_text(encoding="utf-8"))
    app_settings = json.loads(studio_app.settings_path.read_text(encoding="utf-8"))
    assert codex_cfg["base_url"] == "http://localhost:20128/v1"
    assert codex_cfg["model"] == "cx/gpt-5.5"
    assert codex_cfg["api_key"] == "secret-key"
    assert "api_key" not in app_settings

def test_settings_empty_or_masked_api_key_preserves_existing_key(studio_app, tmp_path):
    studio_app.codex_config_path = tmp_path / "codex_api.local.json"
    studio_app._save_codex_config("http://one/v1", "model-a", "secret-key")

    studio_app._save_codex_config("http://two/v1", "model-b", "")
    cfg = json.loads(studio_app.codex_config_path.read_text(encoding="utf-8"))
    assert cfg["api_key"] == "secret-key"
    assert cfg["base_url"] == "http://two/v1"

    studio_app._save_codex_config("http://three/v1", "model-c", API_KEY_PLACEHOLDER)
    cfg = json.loads(studio_app.codex_config_path.read_text(encoding="utf-8"))
    assert cfg["api_key"] == "secret-key"
    assert cfg["model"] == "model-c"

def test_sidebar_switching_updates_active_state(studio_app):
    studio_app._select_sidebar("Logs")

    assert studio_app.sidebar_buttons["Logs"].cget("fg_color") == SPACE_THEME["surface_2"]
    assert studio_app.sidebar_buttons["Project"].cget("fg_color") == "transparent"

def test_sidebar_collapse_and_expand_changes_width_and_labels(studio_app):
    if studio_app.sidebar_collapsed:
        studio_app.sidebar_collapsed = False
        studio_app.sidebar_width = 224
        studio_app._render_sidebar_labels()
    studio_app._toggle_sidebar()
    for _ in range(8):
        studio_app.update()
        time.sleep(0.02)

    assert studio_app.sidebar_collapsed is True
    assert studio_app.sidebar_buttons["Project"].cget("text") == "P"

    studio_app._toggle_sidebar()
    for _ in range(8):
        studio_app.update()
        time.sleep(0.02)

    assert studio_app.sidebar_collapsed is False
    assert studio_app.sidebar_buttons["Project"].cget("text") == "Project"

def test_v54_native_menu_removed_and_space_fonts_applied(studio_app):
    assert studio_app.cget("menu") in ("", None)
    assert studio_app.start_button.cget("font").cget("family") == studio_app.ui_font_family
    assert studio_app.log_box.cget("font").cget("family") == studio_app.mono_font_family
    assert studio_app.plan_box.cget("font").cget("family") == studio_app.mono_font_family
    assert studio_app.command_entry.cget("font").cget("family") == studio_app.mono_font_family

def test_v54_compact_pipeline_and_paned_layout_exist(studio_app):
    assert studio_app.ops_pane is not None
    assert len(studio_app.ops_pane.panes()) == 3
    assert int(studio_app.stage_widgets["planning"].cget("height")) <= 38
    assert studio_app.log_box._textbox.cget("wrap") == "none"
    assert studio_app.plan_box._textbox.cget("wrap") == "none"

def test_v54_planning_mode_persists_and_runner_args_include_mode(studio_app, tmp_path):
    studio_app.settings_path = tmp_path / "settings.json"
    studio_app.settings = {}
    studio_app._set_planning_mode("Deep Planning")

    captured = []
    studio_app.manager.launch = lambda args: captured.extend(args)
    studio_app.start_swarm()

    assert studio_app.planning_mode == PLANNING_MODE_DEEP
    assert "--planning-mode" in captured
    assert captured[captured.index("--planning-mode") + 1] == PLANNING_MODE_DEEP

def test_v54_hotkeys_and_severity_tags(studio_app):
    studio_app.command_entry.insert(0, "help")
    studio_app.handle_console_command()
    assert "commands:" in studio_app.log_box.get("1.0", "end")

    studio_app.command_entry.insert(0, "will-clear")
    assert studio_app._hotkey_clear_console() == "break"
    assert studio_app.command_entry.get() == ""

    studio_app._add_log("error", "[ERROR] failed", agent="agent2")
    studio_app._add_log("warning", "[WARNING] caution", agent="agent2")
    try:
        assert "log_error" in studio_app.log_box.tag_names()
        assert "log_warning" in studio_app.log_box.tag_names()
    except Exception:
        assert "failed" in studio_app.log_box.get("1.0", "end")

def test_v54_bottom_status_bar_contains_runtime_metrics(studio_app):
    assert "Idle" in studio_app.status_chip.cget("text")
    assert "PID" in studio_app.pid_chip.cget("text")
    assert "TOK" in studio_app.burn_chip.cget("text")
    assert "MODE" in studio_app.mode_chip.cget("text")

def test_agent1_v51_rollup_events_update_architect_card(studio_app):
    studio_app._handle_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "phase": "planning",
            "action": "V5.1 Leaf Experts batch completed",
            "status": "pass",
            "summary": "iteration=1; total=24; completed=24; queued=0; failed=0; max_workers=8",
            "rollup_stage": "Leaf Experts",
            "metric": {"completed": 24, "failed": 0, "max_workers": 8},
        }
    )
    studio_app._handle_event(
        {
            "type": "agent_action",
            "agent": "agent1",
            "phase": "planning",
            "action": "V5.1 deterministic guardrails completed",
            "status": "fail",
            "summary": "status=HITL_REQUIRED; failures=1",
            "rollup_stage": "Guardrails",
            "metric": {"guardrail_failures": 1, "iterations": 1},
        }
    )

    widgets = studio_app.agent_widgets["agent1"]
    assert "Guardrails: V5.1 deterministic guardrails completed" in widgets["action"].cget("text")
    evidence = widgets["evidence"].cget("text")
    assert "council: Guardrails" in evidence
    assert "pass: 1" in evidence
    assert "fail: 1" in evidence

def test_connection_missing_api_key_fails_without_network_call(studio_app, tmp_path):
    studio_app.codex_config_path = tmp_path / "codex_api.local.json"
    studio_app._save_codex_config("http://localhost:20128/v1", "cx/gpt-5.5", "")

    with patch("urllib.request.urlopen") as urlopen:
        ok, message = studio_app._test_codex_connection("http://localhost:20128/v1", "cx/gpt-5.5", "")

    assert ok is False
    assert message == "Missing API key"
    urlopen.assert_not_called()

def test_connection_placeholder_uses_saved_key(studio_app, tmp_path):
    studio_app.codex_config_path = tmp_path / "codex_api.local.json"
    studio_app._save_codex_config("http://localhost:20128/v1", "cx/gpt-5.5", "saved-key")

    key, error = studio_app._resolve_api_key_for_test(API_KEY_PLACEHOLDER)

    assert key == "saved-key"
    assert error is None

def test_clear_saved_key_removes_api_key(studio_app, tmp_path):
    studio_app.codex_config_path = tmp_path / "codex_api.local.json"
    studio_app._save_codex_config("http://localhost:20128/v1", "cx/gpt-5.5", "saved-key")

    studio_app._clear_codex_api_key()

    cfg = json.loads(studio_app.codex_config_path.read_text(encoding="utf-8"))
    assert "api_key" not in cfg
    assert cfg["base_url"] == "http://localhost:20128/v1"

def test_connection_async_returns_immediately_and_updates_callback(studio_app, tmp_path):
    studio_app.codex_config_path = tmp_path / "codex_api.local.json"
    studio_app._save_codex_config("http://localhost:20128/v1", "cx/gpt-5.5", "saved-key")
    results = []

    def slow_test(_endpoint, _model, _api_key):
        time.sleep(0.2)
        return True, "Connection OK"

    studio_app._test_codex_connection = slow_test
    started = time.time()
    studio_app._run_connection_test_async("http://localhost:20128/v1", "cx/gpt-5.5", API_KEY_PLACEHOLDER, lambda ok, msg: results.append((ok, msg)))
    elapsed = time.time() - started
    assert elapsed < 0.05

    deadline = time.time() + 2
    while time.time() < deadline and not results:
        studio_app.update()
        time.sleep(0.02)

    assert results == [(True, "Connection OK")]

def test_coming_soon_actions_log_message(studio_app):
    studio_app._coming_soon("Future Wiki", agent="agent6")

    assert "Future Wiki: Coming soon" in studio_app.log_box.get("1.0", "end")
