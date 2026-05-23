try: __import__("ctypes").windll.shcore.SetProcessDpiAwareness(1)
except Exception: pass

"""SWARM AI STUDIO V5.4 desktop app."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import customtkinter as ctk
except ModuleNotFoundError as exc:  # pragma: no cover - exercised manually.
    print("Missing dependency: customtkinter")
    print("Run: .venv_dv\\Scripts\\python.exe -m pip install -r app\\requirements.txt")
    raise SystemExit(1) from exc

from semiconductor_swarm.agents.agent1_planning.architect import derive_project_name, sanitize_project_name

STAGES = ("planning", "rtl", "formal", "hitl", "dv", "physical", "signoff")
STAGE_LABELS = {
    "planning": "Planning",
    "rtl": "RTL",
    "formal": "Formal",
    "hitl": "HITL",
    "dv": "DV",
    "physical": "Physical",
    "signoff": "Signoff",
}
AGENTS = {
    "agent1": ("Agent 1", "Architect"),
    "agent2": ("Agent 2", "RTL Designer"),
    "agent3": ("Agent 3", "DV Engineer"),
    "agent4": ("Agent 4", "Physical"),
    "agent5": ("Agent 5", "Formal"),
    "agent6": ("Agent 6", "Wiki/Signoff"),
}
STATUS_COLORS = {
    "idle": ("#101a2d", "#8293aa"),
    "running": ("#123d68", "#d9f3ff"),
    "paused": ("#593d13", "#ffdf8a"),
    "partial": ("#593d13", "#ffdf8a"),
    "warning": ("#593d13", "#ffdf8a"),
    "pass": ("#0e563d", "#d7ffe5"),
    "fail": ("#5a1822", "#ffd9d9"),
    "error": ("#5a1822", "#ffd9d9"),
    "info": ("#16233a", "#bfd2e8"),
}
LEVEL_COLORS = {
    "error": "#ff4d5e",
    "fail": "#ff4d5e",
    "warning": "#ffb84d",
    "pause": "#ffb84d",
    "done": "#2ee59d",
    "console": "#2ee59d",
    "handoff": "#8a7dff",
    "discussion": "#d7e4f0",
    "metric": "#35d6ff",
    "info": "#2f80ff",
}
SPACE_THEME = {
    "cosmic": "#050812",
    "deep": "#0b1020",
    "panel": "#101a2d",
    "surface": "#121d32",
    "surface_2": "#16233a",
    "border": "#24385a",
    "muted": "#8293aa",
    "text": "#e8f7ff",
    "cyan": "#35d6ff",
    "blue": "#2f80ff",
    "green": "#2ee59d",
    "amber": "#ffb84d",
    "red": "#ff4d5e",
}
LOG_BUFFER_LIMIT = 10_000
LOG_RENDER_LIMIT = 2_000
MAX_QUEUE_BATCH = 100
MAX_UI_TEXT_BYTES = 4 * 1024
UI_FONT_FALLBACKS = ("Segoe UI", "San Francisco", "Helvetica", "Arial")
MONO_FONT_FALLBACKS = ("Cascadia Code", "Consolas", "Courier New", "monospace")
UI_FONT = "Segoe UI"
MONO_FONT = "Cascadia Code" if os.name == "nt" else "Courier New"
CODEX_CONFIG_PATH = ROOT / "codex_api.local.json"
API_KEY_PLACEHOLDER = "********"
SIDEBAR_EXPANDED_WIDTH = 224
SIDEBAR_COLLAPSED_WIDTH = 58
SIDEBAR_ANIMATION_FRAMES = 4
PLANNING_MODE_NORMAL = "normal"
PLANNING_MODE_DEEP = "deep_planning"
PLANNING_MODE_LABELS = {"Normal": PLANNING_MODE_NORMAL, "Deep Planning": PLANNING_MODE_DEEP}
PLANNING_MODE_DISPLAY = {value: label for label, value in PLANNING_MODE_LABELS.items()}
SIDEBAR_LABELS = {
    "Project": "P",
    "Agents": "A",
    "Logs": "L",
    "Plan Review": "R",
    "Settings": "S",
    "Future Wiki": "W",
}

def _installed_font_family(fallbacks: tuple[str, ...]) -> str:
    try:
        families = {family.lower(): family for family in tkfont.families()}
    except Exception:
        families = {}
    for family in fallbacks:
        if family.lower() in families:
            return families[family.lower()]
    return fallbacks[-1]


def _safe_text(value: Any, limit: int = MAX_UI_TEXT_BYTES) -> str:
    text = str(value)
    if len(text.encode("utf-8", errors="replace")) <= limit:
        return text
    encoded = text.encode("utf-8", errors="replace")[: max(0, limit - 64)]
    return encoded.decode("utf-8", errors="ignore") + "\n...[ui truncated]"


class ProcessManager:
    def __init__(self, app: "SwarmStudioApp") -> None:
        self.app = app
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()

    def running(self) -> bool:
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def pid(self) -> str:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return str(self.process.pid)
        return "-"

    def _creationflags(self) -> int:
        return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def launch(self, args: list[str]) -> None:
        if self.running():
            self.app.enqueue({"type": "log", "level": "warning", "message": "runner already active"})
            return
        command = [self.app.python_exe(), str(ROOT / "app" / "swarm_runner.py"), *args]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=self._creationflags(),
        )
        with self.lock:
            self.process = proc
        self.app.enqueue({"type": "log", "level": "info", "message": f"runner pid={proc.pid}"})
        self.app.enqueue({"type": "process_start", "pid": proc.pid})
        threading.Thread(target=self._read_stdout, args=(proc,), daemon=True, name="runner-stdout").start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True, name="runner-stderr").start()
        threading.Thread(target=self._watch, args=(proc,), daemon=True, name="runner-watch").start()

    def stop(self) -> bool:
        with self.lock:
            proc = self.process
        if proc is None or proc.poll() is not None:
            self.app.enqueue({"type": "log", "level": "warning", "message": "no active runner"})
            return True
        self.app.enqueue({"type": "log", "level": "warning", "message": f"stopping pid={proc.pid}"})
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                    creationflags=self._creationflags(),
                )
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return True
        except OSError as exc:
            self.app.enqueue({"type": "log", "level": "error", "message": f"failed to stop runner pid={proc.pid}: {exc}"})
            return False

    def _read_stdout(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                event = {"type": "log", "level": "info", "message": text}
            self.app.enqueue(event)

    def _read_stderr(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.strip()
            if text:
                self.app.enqueue({"type": "log", "level": "error", "message": text})

    def _watch(self, proc: subprocess.Popen[str]) -> None:
        code = proc.wait()
        time.sleep(0.1)
        with self.lock:
            if self.process is proc:
                self.process = None
        self.app.enqueue({"type": "process_exit", "returncode": code})


class SwarmStudioApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SWARM AI STUDIO V5.4")
        self.geometry("1500x900")
        self.minsize(1280, 780)
        self.protocol("WM_DELETE_WINDOW", self.on_exit)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        self.ui_font_family = _installed_font_family(UI_FONT_FALLBACKS)
        self.mono_font_family = _installed_font_family(MONO_FONT_FALLBACKS)

        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.manager = ProcessManager(self)
        self.log_entries: deque[dict[str, str]] = deque(maxlen=LOG_BUFFER_LIMIT)
        self.rendered_log_lines = 0
        self.active_filter = "all"
        self.scroll_locked = False
        self.new_log_count = 0
        self.stage_widgets: dict[str, ctk.CTkLabel] = {}
        self.stage_status = {stage: "idle" for stage in STAGES}
        self.agent_widgets: dict[str, dict[str, Any]] = {}
        self.agent_handoff_counts = {agent: 0 for agent in AGENTS}
        self.sidebar_buttons: dict[str, ctk.CTkButton] = {}
        self.sidebar_frame: ctk.CTkFrame | None = None
        self.sidebar_title: ctk.CTkLabel | None = None
        self.sidebar_subtitle: ctk.CTkLabel | None = None
        self.sidebar_collapsed = False
        self.sidebar_animating = False
        self.sidebar_width = SIDEBAR_EXPANDED_WIDTH
        self.active_sidebar = "Project"
        self.agent1_rollup = self._empty_agent1_rollup()
        self.agent2_rollup = self._empty_agent2_rollup()
        self.codex_metrics = self._empty_codex_metrics()
        self.paused_payload: dict[str, Any] | None = None
        self.pause_action = ""
        self.current_plan_path: Path | None = None
        self.current_output_dir: Path = ROOT / "outputs" / "app_runs" / "studio_demo_soc"
        self.settings_path = ROOT / "app" / "settings.json"
        self.codex_config_path = CODEX_CONFIG_PATH
        self.settings = self._load_settings()
        self.sidebar_collapsed = bool(self.settings.get("sidebar_collapsed", False))
        self.sidebar_width = SIDEBAR_COLLAPSED_WIDTH if self.sidebar_collapsed else SIDEBAR_EXPANDED_WIDTH
        self.planning_mode = str(self.settings.get("planning_mode") or PLANNING_MODE_NORMAL)
        if self.planning_mode not in PLANNING_MODE_DISPLAY:
            self.planning_mode = PLANNING_MODE_NORMAL
        self.ops_pane: tk.PanedWindow | None = None
        self.status_chip: ctk.CTkLabel | None = None
        self.pid_chip: ctk.CTkLabel | None = None
        self.burn_chip: ctk.CTkLabel | None = None
        self.new_log_chip: ctk.CTkLabel | None = None
        self.mode_chip: ctk.CTkLabel | None = None
        self.pulse_on = False

        self._build_ui()
        self._set_defaults()
        self._set_running_ui(False)
        self.after(80, self._drain_events)
        self.after(650, self._pulse_running_steps)

    def python_exe(self) -> str:
        candidate = ROOT / ".venv_dv" / "Scripts" / "python.exe"
        return str(candidate) if candidate.exists() else sys.executable

    def enqueue(self, event: dict[str, Any]) -> None:
        self.events.put(event)

    def _load_settings(self) -> dict[str, Any]:
        if self.settings_path.exists():
            try:
                return json.loads(self.settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_settings(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(self.settings, indent=2, sort_keys=True), encoding="utf-8")

    def _load_codex_config(self) -> dict[str, Any]:
        if self.codex_config_path.exists():
            try:
                data = json.loads(self.codex_config_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_codex_config(self, endpoint: str, model: str, api_key: str = "") -> None:
        current = self._load_codex_config()
        clean_key = api_key.strip()
        next_config = {
            "base_url": endpoint.strip() or current.get("base_url") or "http://localhost:20128/v1",
            "model": model.strip() or current.get("model") or "cx/gpt-5.5",
        }
        if clean_key and clean_key != API_KEY_PLACEHOLDER:
            next_config["api_key"] = clean_key
        elif current.get("api_key"):
            next_config["api_key"] = current["api_key"]
        self.codex_config_path.write_text(json.dumps(next_config, indent=2, sort_keys=True), encoding="utf-8")

    def _clear_codex_api_key(self) -> None:
        current = self._load_codex_config()
        next_config = {key: value for key, value in current.items() if key != "api_key"}
        next_config.setdefault("base_url", self._codex_endpoint())
        next_config.setdefault("model", self._codex_model())
        self.codex_config_path.write_text(json.dumps(next_config, indent=2, sort_keys=True), encoding="utf-8")

    def _mask_key_state(self) -> str:
        return "Saved key: yes" if self._has_codex_api_key() else "Saved key: no"

    def _resolve_api_key_for_test(self, api_key_value: str) -> tuple[str | None, str | None]:
        raw = api_key_value.strip()
        current = self._load_codex_config()
        if raw == API_KEY_PLACEHOLDER:
            saved = current.get("api_key")
            return (str(saved), None) if saved else (None, "Missing API key")
        if raw:
            return raw, None
        saved = current.get("api_key")
        if saved:
            return str(saved), None
        return None, "Missing API key"

    def _codex_endpoint(self) -> str:
        cfg = self._load_codex_config()
        return str(cfg.get("base_url") or self.settings.get("llm_endpoint") or "http://localhost:20128/v1")

    def _codex_model(self) -> str:
        cfg = self._load_codex_config()
        return str(cfg.get("model") or self.settings.get("model") or "cx/gpt-5.5")

    def _has_codex_api_key(self) -> bool:
        return bool(self._load_codex_config().get("api_key"))

    def _ui_font(self, size: int = 12, weight: str | None = None) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.ui_font_family, size=size, weight=weight)

    def _mono_font(self, size: int = 12, weight: str | None = None) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.mono_font_family, size=size, weight=weight)

    def _button_style(self, kind: str) -> dict[str, str]:
        styles = {
            "primary": {"fg_color": SPACE_THEME["cyan"], "hover_color": "#70e6ff", "text_color": "#06111d"},
            "secondary": {"fg_color": SPACE_THEME["surface_2"], "hover_color": "#21375a", "text_color": SPACE_THEME["text"]},
            "success": {"fg_color": "#149765", "hover_color": "#1ecf8a", "text_color": "#06140f"},
            "warning": {"fg_color": "#b97716", "hover_color": SPACE_THEME["amber"], "text_color": "#160f05"},
            "danger": {"fg_color": "#a82434", "hover_color": SPACE_THEME["red"], "text_color": "#fff2f4"},
            "disabled": {"fg_color": "#20293a", "hover_color": "#20293a", "text_color": "#758299"},
        }
        return styles.get(kind, styles["secondary"])

    def _make_button(
        self,
        parent: ctk.CTkBaseClass,
        text: str,
        command: Any,
        kind: str = "secondary",
        *,
        width: int = 110,
        height: int = 36,
        anchor: str = "center",
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            height=height,
            anchor=anchor,
            corner_radius=8,
            border_width=1,
            border_color="#315078",
            font=self._ui_font(12, "bold" if kind == "primary" else None),
            command=command,
            **self._button_style(kind),
        )

    def _build_menu(self) -> None:
        self.config(menu="")

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=self.sidebar_width)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.configure(fg_color=SPACE_THEME["cosmic"])

        self._build_command_bar()
        self._build_sidebar()

        header = ctk.CTkFrame(self, fg_color=SPACE_THEME["deep"], corner_radius=0)
        header.grid(row=1, column=1, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        title_col = ctk.CTkFrame(header, fg_color="transparent")
        title_col.grid(row=0, column=0, sticky="w", padx=18, pady=12)
        ctk.CTkLabel(title_col, text="SWARM AI STUDIO V5.4", font=self._ui_font(25, "bold"), text_color=SPACE_THEME["text"]).pack(anchor="w")
        ctk.CTkLabel(title_col, text="Space-tech semiconductor mission control", font=self._ui_font(12), text_color="#7aa7bd").pack(anchor="w")

        chip_row = ctk.CTkFrame(header, fg_color="transparent")
        chip_row.grid(row=0, column=1, sticky="e", padx=18, pady=12)
        self.output_chip = self._make_button(chip_row, "OPEN OUTPUT", self.open_output, "secondary", width=122, height=32)
        self.output_chip.pack(side="left", padx=4)
        self.jump_button = self._make_button(chip_row, "JUMP TO LATEST", self.jump_latest, "primary", width=132, height=32)
        self.jump_button.pack(side="left", padx=4)
        self.jump_button.configure(state="disabled")

        self._build_inputs()
        self._build_main_area()
        self._build_status_bar()

    def _build_command_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=SPACE_THEME["cosmic"], corner_radius=0, height=42, border_width=1, border_color=SPACE_THEME["border"])
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(6, weight=1)
        for col, (label, command) in enumerate(
            (
                ("File", self.new_project),
                ("Edit", lambda: self._coming_soon("Edit tools")),
                ("View", self.toggle_theme),
                ("Window", lambda: self._select_sidebar("Project")),
                ("Help", lambda: self._coming_soon("Help center")),
                ("Settings", self.open_settings),
            )
        ):
            btn = ctk.CTkButton(
                bar,
                text=label,
                width=72,
                height=30,
                fg_color="transparent",
                hover_color=SPACE_THEME["surface_2"],
                text_color="#c9d6e8",
                font=self._ui_font(12),
                command=command,
            )
            btn.grid(row=0, column=col, padx=(8 if col == 0 else 0, 2), pady=6, sticky="w")
        self.config_chip = ctk.CTkLabel(bar, text=self._settings_summary(), height=26, corner_radius=13, fg_color=SPACE_THEME["surface"], text_color=SPACE_THEME["cyan"], padx=12, font=self._ui_font(12))
        self.config_chip.grid(row=0, column=7, padx=10, pady=8, sticky="e")

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=SPACE_THEME["deep"], corner_radius=0, width=self.sidebar_width, border_width=1, border_color=SPACE_THEME["border"])
        sidebar.grid(row=1, column=0, rowspan=4, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar_frame = sidebar
        top = ctk.CTkFrame(sidebar, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(14, 8))
        top.grid_columnconfigure(0, weight=1)
        self.sidebar_title = ctk.CTkLabel(top, text="SWARM OPS", font=self._ui_font(18, "bold"), text_color=SPACE_THEME["text"])
        self.sidebar_title.grid(row=0, column=0, sticky="w", padx=4)
        self.sidebar_toggle = self._make_button(top, "<", self._toggle_sidebar, "secondary", width=32, height=30)
        self.sidebar_toggle.grid(row=0, column=1, sticky="e")
        self.sidebar_subtitle = ctk.CTkLabel(sidebar, text="V5.4 orbital ops", font=self._ui_font(12), text_color=SPACE_THEME["muted"])
        self.sidebar_subtitle.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 18))
        items = (
            ("Project", lambda: self.requirement_box.focus_set()),
            ("Agents", lambda: self._select_and_filter("all")),
            ("Logs", lambda: self.log_box.focus_set()),
            ("Plan Review", lambda: self.plan_box.focus_set()),
            ("Settings", self.open_settings),
            ("Future Wiki", lambda: self._coming_soon("Agent 6 Wiki Dashboard", agent="agent6")),
        )
        for row, (label, command) in enumerate(items, start=2):
            button = ctk.CTkButton(
                sidebar,
                text=label,
                height=38,
                anchor="w",
                corner_radius=8,
                border_width=1,
                border_color=SPACE_THEME["border"],
                fg_color=SPACE_THEME["surface_2"] if label == self.active_sidebar else "transparent",
                hover_color=SPACE_THEME["surface"],
                text_color=SPACE_THEME["text"] if label == self.active_sidebar else "#c9d6e8",
                font=self._ui_font(12),
                command=lambda name=label, cb=command: (self._select_sidebar(name), cb()),
            )
            button.grid(row=row, column=0, sticky="ew", padx=12, pady=4)
            self.sidebar_buttons[label] = button
        self._render_sidebar_labels()

    def _select_sidebar(self, name: str) -> None:
        self.active_sidebar = name
        for label, button in self.sidebar_buttons.items():
            button.configure(fg_color=SPACE_THEME["surface_2"] if label == name else "transparent", text_color=SPACE_THEME["text"] if label == name else "#c9d6e8")

    def _toggle_sidebar(self) -> None:
        if self.sidebar_animating:
            return
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.settings["sidebar_collapsed"] = self.sidebar_collapsed
        self._save_settings()
        target = SIDEBAR_COLLAPSED_WIDTH if self.sidebar_collapsed else SIDEBAR_EXPANDED_WIDTH
        self._animate_sidebar_width(self.sidebar_width, target, 1)

    def _animate_sidebar_width(self, start: int, target: int, frame: int) -> None:
        self.sidebar_animating = True
        if frame >= SIDEBAR_ANIMATION_FRAMES:
            width = target
        else:
            width = int(start + (target - start) * frame / SIDEBAR_ANIMATION_FRAMES)
        self.sidebar_width = width
        self.grid_columnconfigure(0, minsize=width)
        if self.sidebar_frame is not None:
            self.sidebar_frame.grid_propagate(False)
            self.sidebar_frame.configure(width=width)
        if frame >= SIDEBAR_ANIMATION_FRAMES:
            self.sidebar_animating = False
            self._render_sidebar_labels()
            return
        self.after(18, lambda: self._animate_sidebar_width(start, target, frame + 1))

    def _render_sidebar_labels(self) -> None:
        if hasattr(self, "sidebar_toggle"):
            self.sidebar_toggle.configure(text=">" if self.sidebar_collapsed else "<")
        if self.sidebar_title is not None:
            self.sidebar_title.configure(text="OPS" if self.sidebar_collapsed else "SWARM OPS")
        if self.sidebar_subtitle is not None:
            self.sidebar_subtitle.configure(text="" if self.sidebar_collapsed else "V5.4 orbital ops")
        for label, button in self.sidebar_buttons.items():
            button.configure(text=SIDEBAR_LABELS[label] if self.sidebar_collapsed else label, anchor="center" if self.sidebar_collapsed else "w")

    def _coming_soon(self, feature: str, agent: str = "system") -> None:
        self._add_log("info", f"{feature}: Coming soon", agent=agent)

    def _select_and_filter(self, value: str) -> None:
        self.set_filter(value)
        self.log_box.focus_set()

    def _settings_summary(self) -> str:
        key_state = "key set" if self._has_codex_api_key() else "no key"
        return f"{self._codex_model()} | {key_state}"

    def _chip(self, parent: ctk.CTkBaseClass, text: str, bg: str, fg: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, height=24, corner_radius=3, fg_color=bg, text_color=fg, padx=10, font=self._ui_font(11))
        label.pack(side="left", padx=4)
        return label

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="#06101e", corner_radius=0, height=26, border_width=1, border_color=SPACE_THEME["border"])
        bar.grid(row=4, column=1, sticky="ew")
        bar.grid_columnconfigure(5, weight=1)
        self.status_chip = self._chip(bar, "Idle", "#101a2d", "#9fb5c8")
        self.pid_chip = self._chip(bar, "PID -", "#101a2d", "#8293aa")
        self.burn_chip = self._chip(bar, "TOK 0 | $0.0000 est | 0/min", "#0d261f", "#97ffd8")
        self.new_log_chip = self._chip(bar, "0 new", "#101a2d", SPACE_THEME["cyan"])
        self.mode_chip = self._chip(bar, f"MODE {PLANNING_MODE_DISPLAY.get(self.planning_mode, 'Normal')}", "#101a2d", SPACE_THEME["amber"])

    def _build_inputs(self) -> None:
        panel = ctk.CTkFrame(self, fg_color=SPACE_THEME["panel"], corner_radius=8, border_width=1, border_color=SPACE_THEME["border"])
        panel.grid(row=2, column=1, sticky="ew", padx=14, pady=12)
        panel.grid_columnconfigure(0, weight=3)
        panel.grid_columnconfigure(1, weight=1)
        panel.grid_columnconfigure(2, weight=2)

        req_frame = ctk.CTkFrame(panel, fg_color="transparent")
        req_frame.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=10, pady=10)
        req_frame.grid_rowconfigure(1, weight=1)
        req_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(req_frame, text="Project Requirement", font=self._ui_font(12), text_color=SPACE_THEME["text"]).grid(row=0, column=0, sticky="w")
        self.requirement_box = ctk.CTkTextbox(req_frame, height=96, wrap="none", font=self._mono_font(12), fg_color=SPACE_THEME["cosmic"], text_color=SPACE_THEME["text"], border_width=1, border_color=SPACE_THEME["border"])
        self.requirement_box.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        ctk.CTkLabel(panel, text="Project Name", font=self._ui_font(12), text_color=SPACE_THEME["text"]).grid(row=0, column=1, sticky="w", padx=10, pady=(10, 0))
        self.project_entry = ctk.CTkEntry(panel, fg_color=SPACE_THEME["cosmic"], font=self._ui_font(12), border_color=SPACE_THEME["border"])
        self.project_entry.grid(row=1, column=1, sticky="ew", padx=10, pady=(0, 8))
        self.project_entry.bind("<FocusOut>", lambda _event: self._sanitize_project_name())

        ctk.CTkLabel(panel, text="Run Options").grid(row=2, column=1, sticky="w", padx=10, pady=(0, 0))
        options = ctk.CTkFrame(panel, fg_color="transparent")
        options.grid(row=3, column=1, sticky="ew", padx=10, pady=(0, 10))
        self.demo_chip = ctk.CTkLabel(options, text="DEMO MODE", height=30, corner_radius=15, fg_color="#19324a", text_color="#8fe9ff", padx=12, font=self._ui_font(11))
        self.demo_chip.pack(side="left")

        ctk.CTkLabel(panel, text="Output Directory", font=self._ui_font(12), text_color=SPACE_THEME["text"]).grid(row=0, column=2, sticky="w", padx=10, pady=(10, 0))
        output_row = ctk.CTkFrame(panel, fg_color="transparent")
        output_row.grid(row=1, column=2, sticky="ew", padx=10, pady=(0, 8))
        output_row.grid_columnconfigure(0, weight=1)
        self.output_entry = ctk.CTkEntry(output_row, fg_color=SPACE_THEME["cosmic"], font=self._ui_font(12), border_color=SPACE_THEME["border"])
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._make_button(output_row, "Browse", self.browse_output, "secondary", width=82).grid(row=0, column=1)

        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 10))
        self.start_button = self._make_button(actions, "START SWARM", self.start_swarm, "primary", height=42, width=148)
        self.start_button.pack(side="left", padx=(0, 8))
        self.mode_selector = ctk.CTkSegmentedButton(actions, values=list(PLANNING_MODE_LABELS), command=self._set_planning_mode, font=self._ui_font(12), selected_color=SPACE_THEME["blue"], selected_hover_color="#5aa0ff", unselected_color=SPACE_THEME["surface_2"], unselected_hover_color="#21375a", text_color=SPACE_THEME["text"])
        self.mode_selector.pack(side="left", padx=8)
        self.mode_selector.set(PLANNING_MODE_DISPLAY.get(self.planning_mode, "Normal"))
        self.stop_button = self._make_button(actions, "STOP", self.stop_runner, "danger", height=42, width=92)
        self.stop_button.pack(side="left", padx=8)
        self.resume_button = self._make_button(actions, "APPROVE OK", self.resume_ok, "success", height=42, width=124)
        self.resume_button.pack(side="left", padx=8)
        self.change_button = self._make_button(actions, "REQUEST CHANGE", self.request_change, "warning", height=42, width=150)
        self.change_button.pack(side="left", padx=8)
        self.open_output_button = self._make_button(actions, "OPEN OUTPUT", self.open_output, "secondary", height=42, width=124)
        self.open_output_button.pack(side="left", padx=8)
        self.open_plan_button = self._make_button(actions, "OPEN PLAN", self.open_plan_file, "secondary", height=42, width=112)
        self.open_plan_button.pack(side="left", padx=8)
        self.wiki_button = self._make_button(actions, "OPEN WIKI DASHBOARD", lambda: self._coming_soon("Agent 6 Wiki Dashboard", agent="agent6"), "disabled", height=42, width=176)
        self.wiki_button.pack(side="left", padx=8)
        self.wiki_button.configure(state="disabled")

    def _build_main_area(self) -> None:
        main = ctk.CTkFrame(self, fg_color=SPACE_THEME["cosmic"], corner_radius=0)
        main.grid(row=3, column=1, sticky="nsew", padx=14, pady=(0, 14))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        pipeline = ctk.CTkFrame(main, fg_color=SPACE_THEME["panel"], corner_radius=8, border_width=1, border_color=SPACE_THEME["border"])
        pipeline.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 8))
        for index, stage_name in enumerate(STAGES):
            pipeline.grid_columnconfigure(index, weight=1)
            label = ctk.CTkLabel(pipeline, text=f"o {STAGE_LABELS[stage_name]}  idle", height=36, corner_radius=18, fg_color=SPACE_THEME["surface_2"], text_color=SPACE_THEME["muted"], font=self._ui_font(11, "bold"))
            label.grid(row=0, column=index, sticky="ew", padx=4, pady=6)
            self.stage_widgets[stage_name] = label

        self.ops_pane = tk.PanedWindow(
            main,
            orient="horizontal",
            sashwidth=7,
            sashrelief="flat",
            bg=SPACE_THEME["cosmic"],
            bd=0,
            showhandle=False,
            opaqueresize=True,
        )
        self.ops_pane.grid(row=1, column=0, sticky="nsew")
        self._build_agent_timeline(self.ops_pane)
        self._build_logs_panel(self.ops_pane)
        self._build_right_panel(self.ops_pane)
        self.after(120, self._restore_pane_widths)
        self.ops_pane.bind("<ButtonRelease-1>", self._save_pane_widths)

    def _build_agent_timeline(self, parent: ctk.CTkFrame | tk.PanedWindow) -> None:
        frame = ctk.CTkFrame(parent, fg_color=SPACE_THEME["panel"], corner_radius=8, border_width=1, border_color=SPACE_THEME["border"])
        if isinstance(parent, tk.PanedWindow):
            parent.add(frame, minsize=190, width=285)
        else:
            frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text="Agent Timeline", font=self._ui_font(16, "bold"), text_color=SPACE_THEME["text"]).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))
        for row, (agent, (title, subtitle)) in enumerate(AGENTS.items(), start=1):
            card = ctk.CTkFrame(frame, fg_color=SPACE_THEME["surface"] if agent != "agent6" else "#111720", corner_radius=7, border_width=1, border_color=SPACE_THEME["border"])
            card.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
            card.grid_columnconfigure(0, weight=1)
            name = ctk.CTkLabel(card, text=f"{title} / {subtitle}", font=self._ui_font(13, "bold"), anchor="w", text_color="#dcefff" if agent != "agent6" else "#738292")
            name.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
            status = ctk.CTkLabel(card, text="idle", height=24, corner_radius=12, fg_color="#17202b", text_color="#6f7d8c")
            status.grid(row=0, column=1, sticky="e", padx=10, pady=(8, 0))
            action = ctk.CTkLabel(card, text="Waiting", anchor="w", text_color="#8ca6ba", wraplength=210, justify="left", font=self._ui_font(12))
            action.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(3, 2))
            evidence = ctk.CTkLabel(card, text="evidence: 0 | handoffs: 0", anchor="w", text_color="#607285", font=self._ui_font(11))
            evidence.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 8))
            self.agent_widgets[agent] = {"status": status, "action": action, "evidence": evidence, "evidence_count": 0}

    def _build_logs_panel(self, parent: ctk.CTkFrame | tk.PanedWindow) -> None:
        frame = ctk.CTkFrame(parent, fg_color=SPACE_THEME["panel"], corner_radius=8, border_width=1, border_color=SPACE_THEME["border"])
        if isinstance(parent, tk.PanedWindow):
            parent.add(frame, minsize=340, width=650)
        else:
            frame.grid(row=1, column=1, sticky="nsew", padx=(0, 10))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Real-time Operations Log", font=self._ui_font(16, "bold"), text_color=SPACE_THEME["text"]).grid(row=0, column=0, sticky="w")
        self.filter_control = ctk.CTkSegmentedButton(
            frame,
            values=["all", "agent1", "agent2", "agent3", "agent4", "agent5", "agent6", "errors"],
            command=self.set_filter,
        )
        self.filter_control.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.filter_control.set("all")
        self.log_box = ctk.CTkTextbox(frame, wrap="none", font=self._mono_font(12), fg_color=SPACE_THEME["cosmic"], text_color="#d7e4f0", border_width=1, border_color=SPACE_THEME["border"])
        self.log_box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.log_xscroll = ctk.CTkScrollbar(frame, orientation="horizontal", command=self.log_box.xview)
        self.log_xscroll.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.log_box.configure(xscrollcommand=self.log_xscroll.set)
        self._configure_log_tags()
        self.log_box.configure(state="disabled")
        self.log_box.bind("<MouseWheel>", self._on_log_scroll)
        self.log_box.bind("<Button-4>", self._on_log_scroll)
        self.log_box.bind("<Button-5>", self._on_log_scroll)

    def _build_right_panel(self, parent: ctk.CTkFrame | tk.PanedWindow) -> None:
        frame = ctk.CTkFrame(parent, fg_color=SPACE_THEME["panel"], corner_radius=8, border_width=1, border_color=SPACE_THEME["border"])
        if isinstance(parent, tk.PanedWindow):
            parent.add(frame, minsize=330, width=500)
        else:
            frame.grid(row=1, column=2, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=3)
        frame.grid_rowconfigure(5, weight=1)
        ctk.CTkLabel(frame, text="Architecture Plan Preview", font=self._ui_font(16, "bold"), text_color=SPACE_THEME["text"]).grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.plan_box = ctk.CTkTextbox(frame, wrap="none", font=self._mono_font(12), fg_color=SPACE_THEME["cosmic"], text_color="#d7e4f0", border_width=1, border_color=SPACE_THEME["border"])
        self.plan_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.plan_xscroll = ctk.CTkScrollbar(frame, orientation="horizontal", command=self.plan_box.xview)
        self.plan_xscroll.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.plan_box.configure(xscrollcommand=self.plan_xscroll.set)
        self.plan_box.configure(state="disabled")

        plan_actions = ctk.CTkFrame(frame, fg_color="transparent")
        plan_actions.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        self._make_button(plan_actions, "Approve OK", self.resume_ok, "success").pack(side="left", padx=(0, 6))
        self._make_button(plan_actions, "Request Change", self.request_change, "warning", width=130).pack(side="left", padx=6)
        self._make_button(plan_actions, "Open Plan File", self.open_plan_file, "secondary", width=120).pack(side="left", padx=6)

        ctk.CTkLabel(frame, text="Interactive Console", font=self._ui_font(16, "bold"), text_color=SPACE_THEME["text"]).grid(row=4, column=0, sticky="w", padx=12, pady=(2, 6))
        console_frame = ctk.CTkFrame(frame, fg_color="transparent")
        console_frame.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 12))
        console_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(console_frame, text="root@swarm:~$", font=self._mono_font(12, "bold"), text_color=SPACE_THEME["cyan"]).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.command_entry = ctk.CTkEntry(console_frame, placeholder_text="ok | change <text> | stop | clear | help | open output | open plan | filter errors", font=self._mono_font(12), fg_color=SPACE_THEME["cosmic"], text_color=SPACE_THEME["green"], border_color=SPACE_THEME["border"])
        self.command_entry.grid(row=0, column=1, sticky="ew")
        self.command_entry.bind("<Return>", self.handle_console_command)
        self.command_entry.bind("<Control-Return>", self._hotkey_approve)
        self.command_entry.bind("<Escape>", self._hotkey_clear_console)
        self.bind_all("<Control-Return>", self._hotkey_approve)

    def _set_defaults(self) -> None:
        requirement = "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral"
        project = sanitize_project_name(derive_project_name(requirement), "studio_demo_soc")
        self.requirement_box.insert("1.0", requirement)
        self.project_entry.insert(0, project)
        self.current_output_dir = ROOT / "outputs" / "app_runs" / project
        self.output_entry.insert(0, str(self.current_output_dir))
        self._render_plan_text("Plan preview will appear here when PLAN_REVIEW pauses.")
        self._reset_agents()
        self._add_log("info", "SWARM AI STUDIO V5.4 ready.", agent="system")

    def _sanitize_project_name(self) -> None:
        raw = self.project_entry.get()
        cleaned = sanitize_project_name(raw, "swarm_soc")
        if cleaned != raw:
            self.project_entry.delete(0, "end")
            self.project_entry.insert(0, cleaned)

    def start_swarm(self) -> None:
        self._ensure_codex_config_exists()
        self._sanitize_project_name()
        requirement = self.requirement_box.get("1.0", "end").strip()
        project = self.project_entry.get().strip()
        output_dir = Path(self.output_entry.get().strip() or ROOT / "outputs" / "app_runs" / project)
        if not requirement:
            messagebox.showerror("Missing requirement", "Project Requirement is required.")
            return
        if not project:
            messagebox.showerror("Missing project", "Project Name is required.")
            return
        self.current_output_dir = output_dir
        self.paused_payload = None
        self.pause_action = ""
        self.current_plan_path = None
        self._reset_pipeline()
        self._reset_agents()
        self._reset_codex_metrics()
        self._render_plan_text("Waiting for Plan Review...")
        self._set_running_ui(True)
        args = [
            "start",
            "--requirement",
            requirement,
            "--project-name",
            project,
            "--thread-id",
            self._thread_id(project),
            "--output-dir",
            str(output_dir),
            "--checkpoint-db",
            self._checkpoint_db(),
            "--planning-mode",
            self.planning_mode,
        ]
        self.manager.launch(args)

    def resume_ok(self) -> None:
        if not self.pause_action:
            self._add_log("warning", "no pause is waiting for approval")
            return
        self._launch_resume(notes="ok")

    def request_change(self) -> None:
        dialog = ctk.CTkInputDialog(text="Describe the requested plan/change note:", title="Request Change")
        change = dialog.get_input()
        if change:
            self._launch_resume(notes=change, change=change)

    def _launch_resume(self, notes: str = "ok", change: str = "") -> None:
        if self.manager.running():
            self._add_log("warning", "runner is already active")
            return
        self._ensure_codex_config_exists()
        project = self.project_entry.get().strip() or "swarm_soc"
        output_dir = Path(self.output_entry.get().strip() or ROOT / "outputs" / "app_runs" / project)
        self.current_output_dir = output_dir
        self._set_running_ui(True)
        args = [
            "resume",
            "--project-name",
            project,
            "--thread-id",
            self._thread_id(project),
            "--output-dir",
            str(output_dir),
            "--checkpoint-db",
            self._checkpoint_db(),
            "--notes",
            notes,
            "--resume-action",
            self.pause_action,
            "--planning-mode",
            self.planning_mode,
        ]
        if change:
            args.extend(["--change", change])
        self.manager.launch(args)

    def _set_planning_mode(self, label: str) -> None:
        self.planning_mode = PLANNING_MODE_LABELS.get(label, PLANNING_MODE_NORMAL)
        self.settings["planning_mode"] = self.planning_mode
        self._save_settings()
        if self.mode_chip is not None:
            self.mode_chip.configure(text=f"MODE {PLANNING_MODE_DISPLAY.get(self.planning_mode, 'Normal')}")
        self._add_log("info", f"planning mode: {PLANNING_MODE_DISPLAY.get(self.planning_mode, 'Normal')}", agent="system")

    def stop_runner(self) -> None:
        self.status_chip.configure(text="Stopping", fg_color="#4a1c1c", text_color="#ffd9d9")
        stopped = self.manager.stop()
        if not stopped:
            messagebox.showerror("Stop failed", f"Could not terminate runner PID {self.manager.pid()}. Use Task Manager or taskkill manually.")

    def browse_output(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(ROOT / "outputs"))
        if selected:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, selected)
            self.current_output_dir = Path(selected)

    def open_output(self) -> None:
        path = Path(self.output_entry.get().strip() or self.current_output_dir)
        path.mkdir(parents=True, exist_ok=True)
        self._open_path(path)

    def open_plan_file(self) -> None:
        if self.current_plan_path and self.current_plan_path.exists():
            self._open_path(self.current_plan_path)
        else:
            self._add_log("warning", "no plan file available")

    def _open_path(self, path: Path) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def handle_console_command(self, _event: Any = None) -> None:
        text = self.command_entry.get().strip()
        self.command_entry.delete(0, "end")
        if not text:
            return
        self._add_log("console", f"> {text}", agent="console")
        lower = text.lower()
        if lower in {"ok", "resume ok"}:
            self.resume_ok()
        elif lower.startswith("change "):
            self._launch_resume(notes=text[7:].strip(), change=text[7:].strip())
        elif lower == "stop":
            self.stop_runner()
        elif lower == "clear":
            self.clear_logs()
        elif lower == "help":
            self._add_log("info", "commands: ok | change <text> | stop | clear | help | open output | open plan | filter <name> | jump latest")
        elif lower == "open output":
            self.open_output()
        elif lower == "open plan":
            self.open_plan_file()
        elif lower.startswith("filter "):
            self.set_filter(lower.split(" ", 1)[1].strip())
        elif lower == "jump latest":
            self.jump_latest()
        else:
            self._add_log("warning", f"unknown command: {text}")

    def _hotkey_approve(self, _event: Any = None) -> str:
        self.resume_ok()
        return "break"

    def _hotkey_clear_console(self, _event: Any = None) -> str:
        self.command_entry.delete(0, "end")
        return "break"

    def _restore_pane_widths(self) -> None:
        if self.ops_pane is None:
            return
        widths = self.settings.get("ops_pane_widths")
        if not isinstance(widths, list) or len(widths) != 3:
            return
        try:
            total = max(self.ops_pane.winfo_width(), 1)
            left = max(170, min(int(widths[0]), total - 700))
            middle = max(300, min(int(widths[1]), total - left - 300))
            self.ops_pane.sash_place(0, left, 1)
            self.ops_pane.sash_place(1, left + middle, 1)
        except Exception:
            return

    def _save_pane_widths(self, _event: Any = None) -> None:
        if self.ops_pane is None:
            return
        try:
            panes = self.ops_pane.panes()
            widths = [self.nametowidget(str(pane)).winfo_width() for pane in panes]
        except Exception:
            return
        if len(widths) == 3 and all(width > 0 for width in widths):
            self.settings["ops_pane_widths"] = widths
            self._save_settings()

    def _drain_events(self) -> None:
        count = 0
        while count < MAX_QUEUE_BATCH:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
            count += 1
        delay = 10 if not self.events.empty() else 80
        self.after(delay, self._drain_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "process_start":
            self.pid_chip.configure(text=f"PID {event.get('pid')}")
        elif kind == "log":
            self._add_log(str(event.get("level", "info")), event.get("message", ""), agent=str(event.get("agent", "system")))
        elif kind == "stage":
            self._set_stage(str(event.get("stage")), str(event.get("status", "idle")))
        elif kind == "pause":
            self._handle_pause(event)
        elif kind == "artifact":
            self._handle_artifact(event)
        elif kind == "agent_action":
            self._handle_agent_action(event)
        elif kind == "agent_handoff":
            self._handle_handoff(event)
        elif kind == "agent_discussion":
            self._handle_discussion(event)
        elif kind == "metric":
            self._handle_metric(event)
        elif kind == "done":
            self._add_log("done", f"done: {event.get('status')}", agent="signoff")
            self._set_running_ui(False)
            self.status_chip.configure(text="Done", fg_color="#0d6b3a", text_color="#d7ffe5")
        elif kind == "error":
            self._add_log("error", event.get("message", ""), agent="system")
            if event.get("traceback_tail"):
                self._add_log("error", event.get("traceback_tail", ""), agent="system")
            self._mark_active_fail()
            self._set_running_ui(False)
            self.status_chip.configure(text="Failed", fg_color="#8f1d1d", text_color="#ffd9d9")
        elif kind == "process_exit":
            code = event.get("returncode")
            self._add_log("info", f"runner exited code={code}", agent="system")
            if code not in (0, None):
                self._mark_active_fail()
            self._set_running_ui(False)
            self.pid_chip.configure(text="PID -")
            if self.status_chip.cget("text") == "Stopping":
                self.status_chip.configure(text="Stopped", fg_color="#263244", text_color="#bfd2e8")

    def _handle_pause(self, event: dict[str, Any]) -> None:
        action = str(event.get("action_required", "UNKNOWN"))
        self.pause_action = action
        self.paused_payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        self._add_log("pause", f"pause: {action}", agent="system")
        self.status_chip.configure(text="Paused", fg_color="#8a6100", text_color="#fff0ad")
        plan_path = event.get("plan_path")
        if plan_path:
            self.current_plan_path = Path(str(plan_path))
            self._load_plan_preview(self.current_plan_path)
        self._set_running_ui(False, paused=True)

    def _handle_artifact(self, event: dict[str, Any]) -> None:
        path = _safe_text(event.get("path", ""))
        size = event.get("bytes")
        suffix = f" ({size} bytes)" if size else ""
        self._add_log("info", f"artifact: {path}{suffix}", agent=str(event.get("agent", "system")))
        for agent in AGENTS:
            if agent in path.lower():
                self._bump_agent_evidence(agent)

    def _handle_agent_action(self, event: dict[str, Any]) -> None:
        agent = str(event.get("agent", "agent1"))
        status = str(event.get("status", "info"))
        action = str(event.get("action", "activity"))
        summary = _safe_text(event.get("summary", ""))
        if agent == "agent1" and event.get("rollup_stage"):
            self._update_agent1_rollup(event)
        if agent == "agent2" and event.get("subagent_id"):
            self._update_agent2_rollup(event)
        widgets = self.agent_widgets.get(agent)
        if widgets:
            bg, fg = STATUS_COLORS.get(status, STATUS_COLORS["info"])
            widgets["status"].configure(text=status, fg_color=bg, text_color=fg)
            if agent == "agent1" and event.get("rollup_stage"):
                widgets["action"].configure(text=self._agent1_action_text(event))
                self._refresh_agent_evidence(agent)
            elif agent == "agent2" and event.get("subagent_id"):
                widgets["action"].configure(text=self._agent2_action_text(event))
                self._refresh_agent_evidence(agent)
            else:
                widgets["action"].configure(text=f"{action}: {summary}")
            if event.get("artifact") or event.get("evidence_path"):
                self._bump_agent_evidence(agent)
        self._add_log(status if status in LEVEL_COLORS else "info", f"{agent} {action}: {summary}", agent=agent)

    def _handle_metric(self, event: dict[str, Any]) -> None:
        name = str(event.get("name", "metric"))
        value = event.get("value")
        agent = str(event.get("agent", "system"))
        status = str(event.get("status", "info"))
        self._add_log("metric", f"{name}: {value} [{status}]", agent=agent)
        if name.startswith("codex_"):
            self._update_codex_metrics(name, value)

    def _handle_handoff(self, event: dict[str, Any]) -> None:
        source = str(event.get("from_agent", "agent"))
        target = str(event.get("to_agent", "agent"))
        contract = str(event.get("contract", "contract"))
        summary = _safe_text(event.get("summary", ""))
        if source in self.agent_handoff_counts:
            self.agent_handoff_counts[source] += 1
            self._refresh_agent_evidence(source)
        self._add_log("handoff", f"{source} -> {target} [{contract}]: {summary}", agent=source)

    def _handle_discussion(self, event: dict[str, Any]) -> None:
        speaker = str(event.get("speaker", "agent"))
        audience = str(event.get("audience", "user"))
        message = _safe_text(event.get("message", ""))
        severity = str(event.get("severity", "discussion"))
        self._add_log("discussion" if severity == "info" else severity, f"{speaker} -> {audience}: {message}", agent=speaker)

    def _load_plan_preview(self, path: Path) -> None:
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            self._render_plan_text(text)
            self._add_log("info", f"plan loaded: {path}", agent="agent1")
        else:
            self._render_plan_text(f"Plan file not found:\n{path}")
            self._add_log("warning", f"plan file not found: {path}", agent="agent1")

    def _render_plan_text(self, text: str) -> None:
        self.plan_box.configure(state="normal")
        self.plan_box.delete("1.0", "end")
        self.plan_box.insert("1.0", text)
        self.plan_box.configure(state="disabled")

    def _add_log(self, level: str, message: Any, agent: str = "system") -> None:
        entry = {"level": level.lower(), "message": _safe_text(message), "agent": agent.lower()}
        self.log_entries.append(entry)
        if not self._entry_matches_filter(entry):
            return
        should_scroll = self._log_at_bottom() and not self.scroll_locked
        self.log_box.configure(state="normal")
        line = self._format_log_line(entry)
        self._insert_log_line(line, self._log_tag_for(entry))
        self.rendered_log_lines += line.count("\n")
        if self.rendered_log_lines > LOG_RENDER_LIMIT:
            remove_count = self.rendered_log_lines - LOG_RENDER_LIMIT
            self.log_box.delete("1.0", f"{remove_count + 1}.0")
            self.rendered_log_lines = LOG_RENDER_LIMIT
        if should_scroll:
            self.log_box.see("end")
        else:
            self.scroll_locked = True
            self.new_log_count += 1
            self._update_new_log_chip()
        self.log_box.configure(state="disabled")

    def _configure_log_tags(self) -> None:
        tags = {
            "log_info": LEVEL_COLORS["info"],
            "log_error": LEVEL_COLORS["error"],
            "log_warning": LEVEL_COLORS["warning"],
            "log_metric": LEVEL_COLORS["metric"],
            "log_console": LEVEL_COLORS["console"],
            "log_done": LEVEL_COLORS["done"],
            "log_handoff": LEVEL_COLORS["handoff"],
            "log_neutral": "#d7e4f0",
        }
        for tag, color in tags.items():
            try:
                self.log_box.tag_config(tag, foreground=color)
            except Exception:
                try:
                    self.log_box._textbox.tag_config(tag, foreground=color)
                except Exception:
                    pass

    def _log_tag_for(self, entry: dict[str, str]) -> str:
        level = entry["level"].lower()
        message = entry["message"].upper()
        if level in {"error", "fail"} or "[ERROR]" in message or "[FAIL]" in message:
            return "log_error"
        if level in {"warning", "pause"} or "[WARNING]" in message:
            return "log_warning"
        if level == "metric":
            return "log_metric"
        if level == "console":
            return "log_console"
        if level == "done":
            return "log_done"
        if level == "handoff":
            return "log_handoff"
        if level == "info" or "[INFO]" in message:
            return "log_info"
        return "log_neutral"

    def _insert_log_line(self, line: str, tag: str) -> None:
        try:
            self.log_box.insert("end", line, tag)
        except TypeError:
            self.log_box.insert("end", line)

    def _format_log_line(self, entry: dict[str, str]) -> str:
        level = entry["level"].upper()
        agent = entry["agent"]
        stamp = time.strftime("%H:%M:%S")
        return f"{stamp} [{level:<10}] [{agent:<8}] {entry['message']}\n"

    def _entry_matches_filter(self, entry: dict[str, str]) -> bool:
        if self.active_filter == "all":
            return True
        if self.active_filter == "errors":
            return entry["level"] in {"error", "fail"}
        return entry["agent"] == self.active_filter

    def _render_logs(self) -> None:
        entries = [entry for entry in self.log_entries if self._entry_matches_filter(entry)][-LOG_RENDER_LIMIT:]
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        for entry in entries:
            self._insert_log_line(self._format_log_line(entry), self._log_tag_for(entry))
        self.rendered_log_lines = len(entries)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.scroll_locked = False
        self.new_log_count = 0
        self._update_new_log_chip()

    def _log_at_bottom(self) -> bool:
        try:
            return self.log_box.yview()[1] >= 0.98
        except Exception:
            return True

    def _on_log_scroll(self, _event: Any = None) -> None:
        self.after(40, self._update_scroll_state)

    def _update_scroll_state(self) -> None:
        if self._log_at_bottom():
            self.scroll_locked = False
            self.new_log_count = 0
        else:
            self.scroll_locked = True
        self._update_new_log_chip()

    def jump_latest(self) -> None:
        self.scroll_locked = False
        self.new_log_count = 0
        self.log_box.configure(state="normal")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self._update_new_log_chip()

    def _update_new_log_chip(self) -> None:
        if self.new_log_chip is None:
            return
        self.new_log_chip.configure(text=f"{self.new_log_count} new")
        self.jump_button.configure(state="normal" if self.scroll_locked and self.new_log_count else "disabled")

    def set_filter(self, value: str) -> None:
        if value not in {"all", "agent1", "agent2", "agent3", "agent4", "agent5", "agent6", "errors"}:
            self._add_log("warning", f"unknown filter: {value}")
            return
        self.active_filter = value
        self.filter_control.set(value)
        self._render_logs()

    def clear_logs(self) -> None:
        self.log_entries.clear()
        self.rendered_log_lines = 0
        self.new_log_count = 0
        self.scroll_locked = False
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._update_new_log_chip()

    def _set_stage(self, stage_name: str, status: str) -> None:
        if stage_name not in self.stage_widgets:
            return
        self.stage_status[stage_name] = status
        bg, fg = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
        dot = "*" if status == "running" and self.pulse_on else "o"
        self.stage_widgets[stage_name].configure(text=f"{dot} {STAGE_LABELS[stage_name]}  {status}", fg_color=bg, text_color=fg)

    def _pulse_running_steps(self) -> None:
        self.pulse_on = not self.pulse_on
        for stage_name, status in self.stage_status.items():
            if status == "running":
                self._set_stage(stage_name, status)
        self.after(650, self._pulse_running_steps)

    def _reset_pipeline(self) -> None:
        for stage_name in STAGES:
            self._set_stage(stage_name, "idle")

    def _reset_agents(self) -> None:
        self.agent_handoff_counts = {agent: 0 for agent in AGENTS}
        self.agent1_rollup = self._empty_agent1_rollup()
        self.agent2_rollup = self._empty_agent2_rollup()
        for agent, widgets in self.agent_widgets.items():
            widgets["evidence_count"] = 0
            bg, fg = STATUS_COLORS["idle"]
            widgets["status"].configure(text="reserved" if agent == "agent6" else "idle", fg_color=bg, text_color=fg)
            widgets["action"].configure(text="Reserved for future wiki dashboard" if agent == "agent6" else "Waiting")
            self._refresh_agent_evidence(agent)

    def _bump_agent_evidence(self, agent: str) -> None:
        widgets = self.agent_widgets.get(agent)
        if not widgets:
            return
        widgets["evidence_count"] += 1
        self._refresh_agent_evidence(agent)

    def _refresh_agent_evidence(self, agent: str) -> None:
        widgets = self.agent_widgets.get(agent)
        if not widgets:
            return
        if agent == "agent2":
            rollup = self.agent2_rollup
            widgets["evidence"].configure(
                text=(
                    f"rollup: {rollup['stage']} | latest: {rollup['latest_subagent']} | "
                    f"pass: {rollup['pass']} fail: {rollup['fail']} warn: {rollup['warning']} | "
                    f"artifacts: {rollup['artifacts']} | handoffs: {self.agent_handoff_counts.get(agent, 0)}"
                )
            )
            return
        if agent == "agent1":
            rollup = self.agent1_rollup
            widgets["evidence"].configure(
                text=(
                    f"council: {rollup['stage']} | pass: {rollup['pass']} fail: {rollup['fail']} | "
                    f"conflicts: {rollup['conflicts']} | handoffs: {self.agent_handoff_counts.get(agent, 0)}"
                )
            )
            return
        widgets["evidence"].configure(text=f"evidence: {widgets['evidence_count']} | handoffs: {self.agent_handoff_counts.get(agent, 0)}")

    def _empty_agent1_rollup(self) -> dict[str, Any]:
        return {"stage": "Idle", "pass": 0, "fail": 0, "running": 0, "conflicts": 0, "guardrail_failures": 0}

    def _update_agent1_rollup(self, event: dict[str, Any]) -> None:
        status = str(event.get("status", "info")).lower()
        if status in {"pass", "fail", "running"}:
            self.agent1_rollup[status] += 1
        self.agent1_rollup["stage"] = str(event.get("rollup_stage") or self.agent1_rollup["stage"])
        metric = event.get("metric") if isinstance(event.get("metric"), dict) else {}
        self.agent1_rollup["conflicts"] += self._int_metric(metric.get("critical_conflicts")) + self._int_metric(metric.get("noncritical_conflicts")) + self._int_metric(metric.get("conflicts"))
        self.agent1_rollup["guardrail_failures"] += self._int_metric(metric.get("guardrail_failures"))

    def _empty_agent2_rollup(self) -> dict[str, Any]:
        return {"stage": "Idle", "latest_subagent": "-", "pass": 0, "fail": 0, "warning": 0, "artifacts": 0, "findings": 0}

    def _update_agent2_rollup(self, event: dict[str, Any]) -> None:
        status = str(event.get("status", "info")).lower()
        if status in {"pass", "fail", "warning"}:
            self.agent2_rollup[status] += 1
        self.agent2_rollup["stage"] = str(event.get("rollup_stage") or self.agent2_rollup["stage"])
        self.agent2_rollup["latest_subagent"] = str(event.get("subagent_id") or self.agent2_rollup["latest_subagent"])
        self.agent2_rollup["artifacts"] += self._int_metric(event.get("artifact_count"))
        self.agent2_rollup["findings"] += self._int_metric(event.get("finding_count"))

    def _agent2_action_text(self, event: dict[str, Any]) -> str:
        return (
            f"{event.get('rollup_stage', 'RTL')}: {event.get('subagent_id', '-')} "
            f"{event.get('name', event.get('action', 'activity'))}"
        )

    def _agent1_action_text(self, event: dict[str, Any]) -> str:
        return f"{event.get('rollup_stage', 'Planning')}: {event.get('action', 'activity')}"

    def _empty_codex_metrics(self) -> dict[str, Any]:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0, "burn_rate_tokens_per_min": 0, "first_ts": None}

    def _reset_codex_metrics(self) -> None:
        self.codex_metrics = self._empty_codex_metrics()
        self._update_burn_chip()

    def _update_codex_metrics(self, name: str, value: Any) -> None:
        if self.codex_metrics["first_ts"] is None:
            self.codex_metrics["first_ts"] = time.time()
        if name == "codex_prompt_tokens":
            self.codex_metrics["prompt_tokens"] += self._int_metric(value)
        elif name == "codex_completion_tokens":
            self.codex_metrics["completion_tokens"] += self._int_metric(value)
        elif name == "codex_total_tokens":
            self.codex_metrics["total_tokens"] += self._int_metric(value)
        elif name == "codex_estimated_cost_usd":
            self.codex_metrics["estimated_cost_usd"] += self._float_metric(value)
        elif name == "codex_burn_rate_tokens_per_min":
            self.codex_metrics["burn_rate_tokens_per_min"] = self._int_metric(value)
        self._update_burn_chip()

    def _update_burn_chip(self) -> None:
        total = int(self.codex_metrics.get("total_tokens") or 0)
        if total == 0:
            total = int(self.codex_metrics.get("prompt_tokens") or 0) + int(self.codex_metrics.get("completion_tokens") or 0)
        rate = int(self.codex_metrics.get("burn_rate_tokens_per_min") or 0)
        first_ts = self.codex_metrics.get("first_ts")
        if not rate and first_ts and total:
            elapsed_min = max((time.time() - float(first_ts)) / 60.0, 1 / 60.0)
            rate = int(total / elapsed_min)
        cost = float(self.codex_metrics.get("estimated_cost_usd") or 0.0)
        if self.burn_chip is None:
            return
        self.burn_chip.configure(text=f"TOK {total} | ${cost:.4f} est | {rate}/min")

    def _int_metric(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _float_metric(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _mark_active_fail(self) -> None:
        for stage_name in STAGES:
            if self.stage_status.get(stage_name) in {"running", "paused"}:
                self._set_stage(stage_name, "fail")

    def _set_running_ui(self, running: bool, paused: bool = False) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")
        pause_state = "normal" if paused else "disabled"
        self.resume_button.configure(state=pause_state)
        self.change_button.configure(state=pause_state)
        self.open_plan_button.configure(state="normal" if self.current_plan_path and self.current_plan_path.exists() else "disabled")
        if running:
            self.status_chip.configure(text="Running", fg_color="#0a4f82", text_color="#d9f3ff")
            self.pid_chip.configure(text=f"PID {self.manager.pid()}")
        elif not paused:
            if self.status_chip.cget("text") not in {"Done", "Failed", "Stopping"}:
                self.status_chip.configure(text="Idle", fg_color="#17202b", text_color="#9fb5c8")

    def _thread_id(self, project: str) -> str:
        return f"studio-{sanitize_project_name(project, 'swarm_soc')}"

    def _checkpoint_db(self) -> str:
        return str(self.settings.get("checkpoint_db") or ROOT / ".swarm" / "app_checkpoints.sqlite")

    def _ensure_codex_config_exists(self) -> None:
        if not self.codex_config_path.exists():
            self._save_codex_config(self._codex_endpoint(), self._codex_model(), "")
        self.config_chip.configure(text=self._settings_summary())

    def new_project(self) -> None:
        if self.manager.running() and not messagebox.askyesno("Runner active", "Stop active runner and clear project?"):
            return
        if self.manager.running():
            self.manager.stop()
        self.requirement_box.delete("1.0", "end")
        self.project_entry.delete(0, "end")
        self.output_entry.delete(0, "end")
        self.clear_logs()
        self._reset_pipeline()
        self._reset_agents()
        self._reset_codex_metrics()
        self._render_plan_text("")
        self.status_chip.configure(text="Idle", fg_color="#17202b", text_color="#9fb5c8")

    def toggle_theme(self) -> None:
        current = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Light" if current == "Dark" else "Dark")

    def open_settings(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Studio Settings")
        dialog.geometry("720x390")
        dialog.configure(fg_color="#211815")
        dialog.transient(self)
        dialog.grid_columnconfigure(1, weight=1)
        codex_cfg = self._load_codex_config()

        ctk.CTkLabel(dialog, text="LLM API Endpoint").grid(row=0, column=0, sticky="w", padx=12, pady=(16, 6))
        endpoint = ctk.CTkEntry(dialog, fg_color="#1b2020")
        endpoint.grid(row=0, column=1, sticky="ew", padx=12, pady=(16, 6))
        endpoint.insert(0, self._codex_endpoint())

        ctk.CTkLabel(dialog, text="Model").grid(row=1, column=0, sticky="w", padx=12, pady=6)
        model = ctk.CTkEntry(dialog, fg_color="#1b2020")
        model.grid(row=1, column=1, sticky="ew", padx=12, pady=6)
        model.insert(0, self._codex_model())

        ctk.CTkLabel(dialog, text="API Key").grid(row=2, column=0, sticky="w", padx=12, pady=6)
        api_key = ctk.CTkEntry(dialog, fg_color="#1b2020", show="*")
        api_key.grid(row=2, column=1, sticky="ew", padx=12, pady=6)
        if codex_cfg.get("api_key"):
            api_key.insert(0, API_KEY_PLACEHOLDER)
        key_visible = {"value": False}

        ctk.CTkLabel(dialog, text="Checkpoint DB").grid(row=3, column=0, sticky="w", padx=12, pady=6)
        checkpoint = ctk.CTkEntry(dialog, fg_color="#1b2020")
        checkpoint.grid(row=3, column=1, sticky="ew", padx=12, pady=6)
        checkpoint.insert(0, self._checkpoint_db())

        key_state = ctk.CTkLabel(dialog, text=self._mask_key_state(), text_color="#8fe9ff")
        key_state.grid(row=4, column=0, sticky="w", padx=12, pady=(2, 6))
        status_label = ctk.CTkLabel(dialog, text="API key is masked and never logged.", text_color="#9d9690")
        status_label.grid(row=4, column=1, sticky="w", padx=12, pady=(2, 6))

        def dialog_alive() -> bool:
            try:
                return bool(dialog.winfo_exists())
            except Exception:
                return False

        def toggle_key_visible() -> None:
            key_visible["value"] = not key_visible["value"]
            api_key.configure(show="" if key_visible["value"] else "*")
            show_button.configure(text="Hide" if key_visible["value"] else "Show")

        def clear_key() -> None:
            self._clear_codex_api_key()
            api_key.delete(0, "end")
            key_state.configure(text=self._mask_key_state())
            self.config_chip.configure(text=self._settings_summary())
            status_label.configure(text="Saved API key cleared.", text_color="#ffd36e")

        def test_connection() -> None:
            test_button.configure(state="disabled", text="Testing...")
            status_label.configure(text="Testing connection...", text_color="#8fe9ff")

            def done(ok: bool, message: str) -> None:
                if not dialog_alive():
                    return
                test_button.configure(state="normal", text="Test Connection")
                status_label.configure(text=message, text_color="#98ffbd" if ok else "#ff9b9b")

            self._run_connection_test_async(endpoint.get().strip(), model.get().strip(), api_key.get().strip(), done)

        def save() -> None:
            self._save_codex_config(endpoint.get().strip(), model.get().strip(), api_key.get().strip())
            self.settings["checkpoint_db"] = checkpoint.get().strip()
            self.settings.pop("llm_endpoint", None)
            self.settings.pop("model", None)
            self._save_settings()
            self.config_chip.configure(text=self._settings_summary())
            dialog.destroy()
            self._add_log("info", f"settings saved: endpoint={self._codex_endpoint()} model={self._codex_model()} key={'set' if self._has_codex_api_key() else 'not set'}")

        key_actions = ctk.CTkFrame(dialog, fg_color="transparent")
        key_actions.grid(row=2, column=2, sticky="ew", padx=(0, 12), pady=6)
        show_button = ctk.CTkButton(key_actions, text="Show", width=64, fg_color="#2a2422", hover_color="#37312f", command=toggle_key_visible)
        show_button.pack(side="left", padx=(0, 6))
        ctk.CTkButton(key_actions, text="Clear", width=64, fg_color="#6d2626", hover_color="#8f1d1d", command=clear_key).pack(side="left")

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=5, column=1, columnspan=2, sticky="e", padx=12, pady=18)
        test_button = ctk.CTkButton(actions, text="Test Connection", fg_color="#1c334d", hover_color="#284866", command=test_connection)
        test_button.pack(side="left", padx=(0, 8))
        ctk.CTkButton(actions, text="Save", fg_color="#00a3ff", hover_color="#0076bd", text_color="#04121f", command=save).pack(side="left")

    def _run_connection_test_async(self, endpoint: str, model: str, api_key_value: str, on_done: Any) -> None:
        result_queue: queue.Queue[tuple[bool, str]] = queue.Queue(maxsize=1)

        def poll_result() -> None:
            try:
                ok, message = result_queue.get_nowait()
            except queue.Empty:
                try:
                    if self.winfo_exists():
                        self.after(50, poll_result)
                except Exception:
                    return
                return
            on_done(ok, message)

        def worker() -> None:
            ok, message = self._test_codex_connection(endpoint, model, api_key_value)
            try:
                result_queue.put_nowait((ok, message))
            except queue.Full:
                pass

        threading.Thread(target=worker, name="codex-connection-test", daemon=True).start()
        self.after(50, poll_result)

    def _test_codex_connection(self, endpoint: str, model: str, api_key_value: str) -> tuple[bool, str]:
        import urllib.error
        import urllib.request

        key, error = self._resolve_api_key_for_test(api_key_value)
        if error:
            return False, error
        base_url = (endpoint or "http://localhost:20128/v1").rstrip("/")
        payload = json.dumps({"model": model or "cx/gpt-5.5", "messages": [{"role": "user", "content": "ping"}], "temperature": 0}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(f"{base_url}/chat/completions", data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            return bool(content), "Connection OK" if content else "Connection reached endpoint but response was empty"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            return False, f"Connection failed: {type(exc).__name__}"

    def on_exit(self) -> None:
        if self.manager.running():
            if not messagebox.askyesno("Runner active", "Stop active runner and exit?"):
                return
            self.status_chip.configure(text="Stopping", fg_color="#4a1c1c", text_color="#ffd9d9")
            stopped = self.manager.stop()
            if not stopped:
                messagebox.showerror("Stop failed", f"Could not terminate runner PID {self.manager.pid()}. Run taskkill manually.")
                return
        self.destroy()


def main() -> None:
    app = SwarmStudioApp()
    app.mainloop()


if __name__ == "__main__":
    main()
