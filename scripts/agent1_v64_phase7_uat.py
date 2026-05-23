"""Manual-style Phase 7 UAT harness for Agent 1 V6.4 Studio flow.

This uses a local fake OpenAI-compatible endpoint so UAT does not expose or spend
the owner's API key. It still drives the real Studio backend, frontend, runner,
checkpoint flow, artifacts, and browser screenshots.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv_dv" / "Scripts" / "python.exe"
CODEX_CONFIG = ROOT / "codex_api.local.json"
STUDIO_SETTINGS = ROOT / "studio" / "settings.json"
EDGE_CANDIDATES = (
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_response(content: str) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 31, "completion_tokens": 17, "total_tokens": 48},
        }
    ).encode("utf-8")


def _canonical(requirement: str) -> dict[str, Any]:
    text = requirement.lower()
    power = "<1W" if any(token in text for token in ("<1w", "under 1w", "duoi 1w", "dưới 1w")) else None
    if "uart" in text:
        return {
            "purpose": "UART APB controller",
            "cpu": None,
            "bus": {"protocol": "APB"},
            "peripheral": ["uart"],
            "accelerator": None,
            "clock": {"frequency_mhz": 50},
            "power": power,
            "node": None,
            "memory": None,
            "interrupts": {"uart_irq": True},
            "verification_scope": "formal-first",
            "custom_ip": "uart_apb_controller",
        }
    return {
        "purpose": "AI camera chip",
        "cpu": None,
        "bus": {"protocol": "APB"},
        "peripheral": [],
        "accelerator": "int8_mac_array",
        "clock": {"frequency_mhz": 100},
        "power": power,
        "node": None,
        "memory": None,
        "interrupts": None,
        "verification_scope": "formal-first",
        "custom_ip": None,
    }


def _extract_requirement(prompt: str) -> str:
    marker = "Raw user requirement:"
    if marker in prompt:
        return prompt.split(marker, 1)[1].splitlines()[0].strip()
    for line in prompt.splitlines():
        if "tao chip" in line.lower() or "uart apb" in line.lower() or line.strip().lower() in {"hi", "hi, ban la ai", "hi, bạn là ai"}:
            return line.strip()
    return prompt[:1000]


def _intake_payload(prompt: str) -> dict[str, Any]:
    requirement = _extract_requirement(prompt)
    text = requirement.lower()
    has_design = any(token in text for token in ("chip", "apb", "uart", "controller", "100mhz", "50mhz"))
    if not has_design:
        canonical = {key: None for key in _canonical("").keys()}
        return {
            "classification": "NON_DESIGN_CONVERSATION",
            "normalized_requirement": "",
            "canonical_intent": canonical,
            "extracted_intent": {},
            "missing_fields": ["chip purpose", "CPU/IP/peripheral intent", "bus/protocol", "clock"],
            "user_response": "Agent 1 needs a chip design requirement before architecture planning.",
            "brief_form": {"chip_purpose": "", "bus_protocol": "", "cpu_ip_peripheral": "", "clock": "", "power": "", "target_flow": ""},
            "citations": [{"source": "raw_requirement", "field": "non_design", "text": requirement}],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.96,
        }
    canonical = _canonical(requirement)
    citations = [
        {"source": "raw_requirement", "field": "purpose", "text": str(canonical["purpose"])},
        {"source": "raw_requirement", "field": "bus", "text": "APB"},
        {"source": "raw_requirement", "field": "clock", "text": str(canonical["clock"])},
    ]
    for field in ("peripheral", "accelerator", "custom_ip"):
        if canonical.get(field):
            citations.append({"source": "raw_requirement", "field": field, "text": str(canonical[field])})
    if canonical.get("power"):
        citations.append({"source": "raw_requirement", "field": "power", "text": str(canonical["power"])})
    return {
        "classification": "DESIGN_READY",
        "normalized_requirement": requirement,
        "canonical_intent": canonical,
        "extracted_intent": canonical,
        "missing_fields": [],
        "user_response": "Design-ready requirement accepted.",
        "brief_form": {
            "chip_purpose": canonical["purpose"],
            "bus_protocol": "APB",
            "cpu_ip_peripheral": canonical.get("custom_ip") or canonical.get("accelerator") or canonical.get("peripheral"),
            "clock": canonical["clock"],
            "power": canonical.get("power"),
            "target_flow": "formal-first",
        },
        "citations": citations,
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.92,
    }


def _council_payload(prompt: str) -> dict[str, Any]:
    requirement = _extract_requirement(prompt)
    canonical = _canonical(requirement)
    return {
        "summary": "UAT council preserved the canonical user requirement.",
        "decisions": [{"decision": "preserve_canonical_intent", "value": canonical}],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "conflicts": [],
        "citations": [{"source": "raw_requirement", "field": "purpose"}],
        "confidence": 0.91,
        "needs_revision": False,
        "selected_architecture_candidate": {
            "summary": canonical["purpose"],
            "primary_protocol": "APB",
            "external_peripherals": canonical.get("peripheral") or [],
            "cpu_width": None,
        },
        "requirements_preserved": True,
        "plan_ready_candidate": True,
    }


def _completion_for(prompt: str) -> str:
    if "Respond with OK only" in prompt:
        return "OK"
    if "Agent 2 Codex RTL Review" in prompt:
        return json.dumps({"summary": "UAT RTL review passed with no findings.", "findings": []})
    if "Agent 2 Codex RTL Implementation Plan" in prompt:
        return "UAT Agent2 plan: preserve locked APB contract and use pattern_manifest rules."
    if "Agent 1 V6.4 Intake" in prompt or "Agent 1 V6.4 JSON Repair" in prompt or "Intake Adjudicator" in prompt:
        return json.dumps(_intake_payload(prompt))
    return json.dumps(_council_payload(prompt))


class FakeCodexHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
            prompt = str(payload.get("messages", [{}])[0].get("content", ""))
        except Exception:
            prompt = ""
        content = _completion_for(prompt)
        data = _json_response(content)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


@contextlib.contextmanager
def fake_codex_server(port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeCodexHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def backed_up_configs(fake_endpoint: str, output_root: Path, checkpoint_db: Path):
    backup_dir = Path(tempfile.mkdtemp(prefix="agent1_v64_uat_config_"))
    backups: dict[Path, Path] = {}
    for path in (CODEX_CONFIG, STUDIO_SETTINGS):
        if path.exists():
            target = backup_dir / path.name
            shutil.copy2(path, target)
            backups[path] = target
    try:
        CODEX_CONFIG.write_text(json.dumps({"base_url": fake_endpoint, "model": "uat/mock-codex", "api_key": "uat-local-key"}, indent=2), encoding="utf-8")
        STUDIO_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        STUDIO_SETTINGS.write_text(
            json.dumps({"checkpoint_db": str(checkpoint_db), "output_root": str(output_root), "active_key_ref": "owner"}, indent=2),
            encoding="utf-8",
        )
        yield
    finally:
        for path in (CODEX_CONFIG, STUDIO_SETTINGS):
            if path in backups:
                shutil.copy2(backups[path], path)
            elif path.exists():
                path.unlink()
        shutil.rmtree(backup_dir, ignore_errors=True)


def _start_process(cmd: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> subprocess.Popen[str]:
    handle = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=handle, stderr=subprocess.STDOUT, text=True)


def _wait_url(url: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception as exc:
            last = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last}")


def _request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body}
        return exc.code, parsed


def _poll_state(api_base: str, predicate, timeout_s: float = 90.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    while time.time() < deadline:
        _, state = _request_json(f"{api_base}/api/runs/current_state")
        if predicate(state):
            return state
        time.sleep(0.5)
    return state


def _edge_path() -> Path:
    for path in EDGE_CANDIDATES:
        if path.is_file():
            return path
    raise RuntimeError("No Edge/Chrome executable found for screenshots.")


def _screenshot(frontend_url: str, output_path: Path) -> bool:
    edge = _edge_path()
    profile_dir = output_path.parent / "browser_profile"
    profile_dir.mkdir(exist_ok=True)
    cmd = [
        str(edge),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        f"--user-data-dir={profile_dir}",
        "--window-size=1440,1000",
        "--virtual-time-budget=3000",
        f"--screenshot={output_path}",
        frontend_url,
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=30)
    if result.returncode != 0:
        (output_path.with_suffix(".stderr.txt")).write_text(result.stderr + "\n" + result.stdout, encoding="utf-8")
    return output_path.is_file()


def _artifact_summary(output_dir: Path) -> dict[str, Any]:
    reports = output_dir / "reports"
    agent1 = reports / "agent1"
    return {
        "architecture_plan_exists": (reports / "architecture_plan.md").is_file(),
        "clarification_exists": (reports / "agent1_requirement_clarification.md").is_file(),
        "intake_report_exists": (agent1 / "agent1_intake_router_report.json").is_file(),
        "agent2_dir_exists": (output_dir / "rtl").exists(),
        "signoff_ready_in_status_log": "SIGNOFF_READY" in ((output_dir / "status.log").read_text(encoding="utf-8", errors="ignore") if (output_dir / "status.log").is_file() else ""),
    }


def run_uat(evidence_dir: Path) -> dict[str, Any]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    output_root = evidence_dir / "studio_runs"
    checkpoint_db = evidence_dir / "uat_checkpoints.sqlite"
    fake_port = _free_port()
    backend_port = _free_port()
    frontend_port = _free_port()
    api_base = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}/"
    fake_endpoint = f"http://127.0.0.1:{fake_port}/v1"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    frontend_env = {**env, "VITE_STUDIO_API_BASE": api_base}
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    backend_log = evidence_dir / "backend.log"
    frontend_log = evidence_dir / "frontend.log"
    backend_proc: subprocess.Popen[str] | None = None
    frontend_proc: subprocess.Popen[str] | None = None
    report: dict[str, Any] = {
        "schema_version": "agent1.v64.phase7_uat_report.v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "fake_codex_endpoint": fake_endpoint,
        "api_base": api_base,
        "frontend_url": frontend_url,
        "cases": [],
    }
    with fake_codex_server(fake_port), backed_up_configs(fake_endpoint, output_root, checkpoint_db):
        backend_proc = _start_process([str(PYTHON), "-m", "uvicorn", "studio.backend.server:app", "--host", "127.0.0.1", "--port", str(backend_port)], ROOT, env, backend_log)
        frontend_proc = _start_process([npm, "run", "dev", "--prefix", "studio/frontend", "--", "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"], ROOT, frontend_env, frontend_log)
        try:
            _wait_url(f"{api_base}/api/health")
            _wait_url(frontend_url)
            cases = [
                ("hi", "hi", "REQUIREMENT_CLARIFICATION"),
                ("hi_ban_la_ai", "Hi, ban la ai", "REQUIREMENT_CLARIFICATION"),
                ("ai_camera", "Tao chip AI camera APB 100MHz", "PLAN_REVIEW"),
                ("mixed_uart", "ban la ai, tao UART APB controller 50MHz", "PLAN_REVIEW"),
            ]
            for case_id, requirement, expected_action in cases:
                output_dir = output_root / case_id
                payload = {
                    "requirement": requirement,
                    "project_name": case_id,
                    "output_dir": str(output_dir),
                    "planning_mode": "normal",
                    "checkpoint_db": str(checkpoint_db),
                    "apiKeyRef": "owner",
                }
                status, body = _request_json(f"{api_base}/api/runs/start", "POST", payload)
                state = _poll_state(api_base, lambda item: bool(item.get("pause")) or item.get("status") in {"failed", "done"})
                action = (state.get("pause") or {}).get("action_required")
                case_dir = evidence_dir / case_id
                case_dir.mkdir(exist_ok=True)
                screenshot_path = case_dir / "studio.png"
                screenshot_ok = _screenshot(frontend_url, screenshot_path)
                (case_dir / "start_response.json").write_text(json.dumps({"status": status, "body": body}, indent=2, sort_keys=True), encoding="utf-8")
                (case_dir / "current_state.json").write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
                summary = {
                    "case": case_id,
                    "requirement": requirement,
                    "expected_action": expected_action,
                    "actual_action": action,
                    "status_code": status,
                    "state_status": state.get("status"),
                    "output_dir": str(output_dir),
                    "artifacts": _artifact_summary(output_dir),
                    "screenshot": str(screenshot_path),
                    "screenshot_ok": screenshot_ok,
                    "pass": status == 200 and action == expected_action,
                }
                if case_id == "ai_camera" and summary["pass"] and state.get("run_id"):
                    resume_payload = {"notes": "ok", "resume_action": action, "planning_mode": "normal", "apiKeyRef": "owner"}
                    last_event_id = int(state.get("last_event_id") or 0)
                    last_pause_event_id = int((state.get("pause") or {}).get("event_id") or 0)
                    r_status, r_body = _request_json(f"{api_base}/api/runs/{state['run_id']}/resume", "POST", resume_payload)
                    resumed_state = _poll_state(
                        api_base,
                        lambda item: int(item.get("last_event_id") or 0) > last_event_id
                        and (
                            int((item.get("pause") or {}).get("event_id") or 0) > last_pause_event_id
                            or item.get("status") in {"done", "failed", "stopped"}
                        ),
                        timeout_s=150.0,
                    )
                    post_resume_action = (resumed_state.get("pause") or {}).get("action_required")
                    (case_dir / "resume_response.json").write_text(json.dumps({"status": r_status, "body": r_body}, indent=2, sort_keys=True), encoding="utf-8")
                    (case_dir / "resumed_state.json").write_text(json.dumps(resumed_state, indent=2, sort_keys=True), encoding="utf-8")
                    summary["resume_status_code"] = r_status
                    summary["resumed_state_status"] = resumed_state.get("status")
                    summary["post_resume_action"] = post_resume_action
                    summary["resumed_artifacts"] = _artifact_summary(output_dir)
                    summary["pass"] = bool(
                        summary["pass"]
                        and r_status == 200
                        and (
                            post_resume_action == "HUMAN_REVIEW"
                            or resumed_state.get("status") in {"done", "stopped"}
                        )
                    )
                report["cases"].append(summary)

            repeated_payload = {
                "requirement": "Tao chip AI camera APB 100MHz",
                "project_name": "ai_camera",
                "output_dir": str(output_root / "ai_camera"),
                "planning_mode": "normal",
                "checkpoint_db": str(checkpoint_db),
                "apiKeyRef": "owner",
            }
            repeat_status, repeat_body = _request_json(f"{api_base}/api/runs/start", "POST", repeated_payload)
            repeat_dir = evidence_dir / "repeated_start_same_project"
            repeat_dir.mkdir(exist_ok=True)
            repeat_shot = repeat_dir / "studio.png"
            repeat_shot_ok = _screenshot(frontend_url, repeat_shot)
            (repeat_dir / "start_response.json").write_text(json.dumps({"status": repeat_status, "body": repeat_body}, indent=2, sort_keys=True), encoding="utf-8")
            report["cases"].append(
                {
                    "case": "repeated_start_same_project",
                    "expected_status": 409,
                    "actual_status": repeat_status,
                    "expected_detail_contains": "OUTPUT_EXISTS",
                    "actual_detail": repeat_body.get("detail"),
                    "screenshot": str(repeat_shot),
                    "screenshot_ok": repeat_shot_ok,
                    "pass": repeat_status == 409 and "OUTPUT_EXISTS" in str(repeat_body.get("detail")),
                }
            )
        finally:
            for proc in (frontend_proc, backend_proc):
                if proc and proc.poll() is None:
                    proc.terminate()
            for proc in (frontend_proc, backend_proc):
                if proc and proc.poll() is None:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
    report["pass"] = all(bool(item.get("pass")) for item in report["cases"])
    (evidence_dir / "uat_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", default=str(ROOT / "outputs" / "uat_evidence" / f"agent1_v64_phase7_{datetime.now().strftime('%Y%m%d_%H%M%S')}"))
    args = parser.parse_args(argv)
    report = run_uat(Path(args.evidence_dir))
    print(json.dumps({"pass": report["pass"], "evidence_dir": str(Path(args.evidence_dir)), "cases": [{k: v for k, v in item.items() if k in {"case", "pass", "expected_action", "actual_action", "actual_status"}} for item in report["cases"]]}, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
