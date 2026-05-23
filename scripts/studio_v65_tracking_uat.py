"""Extended Studio V6.5 tracking UAT harness.

The harness drives the real FastAPI backend, React frontend, subprocess runner,
Agent 1 intake/council graph, artifact writers, and trace reports. It uses a
local OpenAI-compatible fake endpoint so broad sweeps do not expose or spend the
owner credential.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
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
TRACE_FILES_REQUIRED = (
    "agent1_intake_trace.jsonl",
    "agent1_canonical_trace.jsonl",
    "agent1_defaults_trace.jsonl",
    "agent1_final_decision_trace.jsonl",
    "agent1_completion_trace.jsonl",
    "trace_health_report.json",
    "trace_invariant_report.json",
)
TRACE_FILES_REQUIRED_BY_ACTION = {
    "REQUIREMENT_CLARIFICATION": (
        "agent1_intake_trace.jsonl",
        "agent1_completion_trace.jsonl",
        "agent1_council_trace.jsonl",
        "agent1_state_snapshots.jsonl",
        "trace_health_report.json",
        "trace_invariant_report.json",
    ),
    "PLAN_REVIEW": TRACE_FILES_REQUIRED,
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_response(content: str) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 41, "completion_tokens": 29, "total_tokens": 70},
        }
    ).encode("utf-8")


def _extract_requirement(prompt: str) -> str:
    fenced_patterns = (
        r"User requirement data:\s*```(?:text)?\s*(.*?)\s*```",
        r"Raw user requirement:\s*```(?:text)?\s*(.*?)\s*```",
        r"User requirement:\s*```(?:text)?\s*(.*?)\s*```",
    )
    for pattern in fenced_patterns:
        match = re.search(pattern, prompt, flags=re.I | re.S)
        if match:
            clean = match.group(1).strip().strip('"')
            if clean:
                return clean
    for marker in ("Raw user requirement:", "User requirement:", '"requirement":', "requirement':"):
        if marker in prompt:
            after = prompt.split(marker, 1)[1]
            for line in after.splitlines():
                clean = line.strip().strip('",')
                lower = clean.lower()
                if clean and not lower.startswith(("project label", "expert id", "return strict json", "schema errors")):
                    return clean
    for line in prompt.splitlines():
        clean = line.strip()
        lower = clean.lower()
        if lower.startswith(("project label", "expert id", "# agent", "return strict json", "separate real chip", "extract explicit", "decide whether", "produce a concise")):
            continue
        if any(token in lower for token in ("ban la ai", "ban may tuoi", "cpu", "apb", "axi", "uart", "chip", "controller")):
            return clean
    return prompt[:1000]


def _canonical(requirement: str) -> dict[str, Any]:
    text = requirement.lower()
    has_cpu = bool(re.search(r"\b(cpu|processor|rv32|rv64|32-bit|32 bit)\b", text))
    width = 32 if "32" in text or "rv32" in text else None
    bus = "AXI" if "axi" in text and "apb" not in text else ("APB" if "apb" in text else None)
    if "apb only" in text:
        bus = "APB"
    peripherals = [name for name in ("uart", "spi", "i2c", "gpio") if re.search(rf"\b{name}\b", text)]
    clock = {"frequency_mhz": 100 if "100mhz" in text or "100 mhz" in text else (50 if "50mhz" in text or "50 mhz" in text else None)}
    custom_ip = "uart_apb_controller" if "uart" in peripherals and ("controller" in text or "apb" in text) else None
    purpose = "32-bit CPU architecture" if has_cpu else ("UART APB controller" if custom_ip else ("chip architecture" if "chip" in text else ""))
    return {
        "purpose": purpose,
        "cpu": {"width_bits": width or 32, "isa": "rv32imc"} if has_cpu else None,
        "bus": {"protocol": bus or "APB"} if (bus or peripherals or has_cpu or "chip" in text) else None,
        "peripheral": peripherals,
        "accelerator": "int8_mac_array" if "camera" in text or "vision" in text else None,
        "clock": clock if clock["frequency_mhz"] else None,
        "power": None,
        "node": None,
        "memory": {"rom": "boot_rom", "sram": "single_port_sram", "cache": "none"} if has_cpu else None,
        "interrupts": {"uart_irq": True} if "uart" in peripherals else None,
        "verification_scope": "formal-first" if has_cpu or peripherals or "chip" in text else None,
        "custom_ip": custom_ip,
    }


def _intake_payload(prompt: str) -> dict[str, Any]:
    requirement = _extract_requirement(prompt)
    text = requirement.lower()
    is_social = any(token in text for token in ("hi", "ban la ai", "ban may tuoi", "may tuoi")) and not any(token in text for token in ("cpu", "apb", "axi", "uart", "controller", "chip"))
    contradiction = "apb only" in text and "axi" in text
    has_design = any(token in text for token in ("cpu", "apb", "axi", "uart", "controller", "chip", "100mhz", "50mhz"))
    canonical = _canonical(requirement)
    if is_social or not has_design:
        return {
            "classification": "NON_DESIGN_CONVERSATION",
            "normalized_requirement": "",
            "canonical_intent": {key: None for key in canonical},
            "extracted_intent": {},
            "missing_fields": ["chip purpose", "CPU/IP/peripheral intent", "bus/protocol", "clock"],
            "user_response": "Agent 1 needs a chip design requirement before architecture planning.",
            "brief_form": {"chip_purpose": "", "bus_protocol": "", "cpu_ip_peripheral": "", "clock": "", "power": "", "target_flow": ""},
            "citations": [{"source": "raw_requirement", "field": "non_design", "text": requirement}],
            "conflicts": [],
            "contradictions": [],
            "confidence": 0.96,
        }
    if contradiction:
        return {
            "classification": "DESIGN_NEEDS_CLARIFICATION",
            "normalized_requirement": requirement,
            "canonical_intent": canonical,
            "extracted_intent": canonical,
            "missing_fields": ["resolve APB-only versus AXI bus contradiction"],
            "user_response": "Requirement mixes APB-only and AXI. Pick one bus before architecture planning.",
            "brief_form": {"chip_purpose": canonical["purpose"], "bus_protocol": "APB/AXI conflict", "cpu_ip_peripheral": canonical["peripheral"], "clock": canonical["clock"], "power": "", "target_flow": "formal-first"},
            "citations": [{"source": "raw_requirement", "field": "bus", "text": requirement}],
            "conflicts": [{"severity": "critical", "type": "bus_conflict", "message": "APB-only conflicts with AXI."}],
            "contradictions": [{"type": "bus_conflict", "message": "APB-only conflicts with AXI."}],
            "confidence": 0.94,
        }
    classification = "MIXED" if "ban la ai" in text or "ban may tuoi" in text else "DESIGN_READY"
    citations = [
        {"source": "raw_requirement", "field": "purpose", "text": requirement},
        {"source": "raw_requirement", "field": "bus", "text": requirement},
    ]
    if canonical.get("cpu"):
        citations.append({"source": "raw_requirement", "field": "cpu", "text": requirement})
    if canonical.get("peripheral"):
        citations.append({"source": "raw_requirement", "field": "peripheral", "text": requirement})
    if canonical.get("custom_ip"):
        citations.append({"source": "raw_requirement", "field": "custom_ip", "text": requirement})
    return {
        "classification": classification,
        "normalized_requirement": requirement,
        "canonical_intent": canonical,
        "extracted_intent": canonical,
        "missing_fields": [],
        "user_response": "Design-ready requirement accepted.",
        "brief_form": {
            "chip_purpose": canonical["purpose"],
            "bus_protocol": canonical.get("bus", {}).get("protocol") if isinstance(canonical.get("bus"), dict) else "",
            "cpu_ip_peripheral": canonical.get("custom_ip") or canonical.get("peripheral") or canonical.get("accelerator"),
            "clock": canonical.get("clock"),
            "power": canonical.get("power"),
            "target_flow": "formal-first",
        },
        "citations": citations,
        "conflicts": [],
        "contradictions": [],
        "confidence": 0.93,
    }


def _council_payload(prompt: str) -> dict[str, Any]:
    requirement = _extract_requirement(prompt)
    canonical = _canonical(requirement)
    text = requirement.lower()
    conflicts: list[dict[str, Any]] = []
    if "Leaf L12" in prompt and "uart" in text and "spi" not in text:
        conflicts.append(
            {
                "severity": "critical",
                "conflict": "Leaf asks for SPI external peripheral planning, but project requirement and deterministic intents declare UART external peripheral only",
                "needed_decision": "Confirm SPI addition or retask leaf to UART",
                "resolution_status": "open",
            }
        )
    if "V5.1 Middle Manager M02" in prompt and "cpu" in text:
        conflicts.extend(
            [
                {"severity": "critical", "description": "Reset/trap vector addresses missing.", "domain": "reset_boot_trap"},
                {"severity": "critical", "description": "boot_rom, single_port_sram, uart_apb_controller base addresses/sizes missing.", "domain": "memory_map"},
            ]
        )
    selected = {
        "summary": canonical.get("purpose") or "Architecture candidate",
        "primary_protocol": canonical.get("bus", {}).get("protocol", "APB") if isinstance(canonical.get("bus"), dict) else "APB",
        "external_peripherals": canonical.get("peripheral") or [],
        "cpu_width_bits": (canonical.get("cpu") or {}).get("width_bits") if isinstance(canonical.get("cpu"), dict) else None,
    }
    return {
        "summary": "UAT council preserved the canonical user requirement.",
        "decisions": [{"decision": "preserve_canonical_intent", "value": canonical}],
        "accepted_decisions": [{"decision": "preserve_canonical_intent", "value": canonical}],
        "rejected_decisions": [],
        "domain_summary": "UAT domain summary.",
        "domain_conflicts": conflicts,
        "feedback_to_leaf_experts": {},
        "handoff_to_principal": ["Preserve explicit requirement and default only open architecture values."],
        "assumptions": [],
        "open_questions": [],
        "risks": [],
        "conflicts": conflicts,
        "citations": [{"source": "raw_requirement", "field": "purpose"}],
        "confidence": 0.91,
        "needs_revision": bool(conflicts),
        "selected_architecture_candidate": selected,
        "rejected_alternatives": [],
        "resolved_conflicts": conflicts,
        "unresolved_conflicts": [],
        "feedback_to_middle_managers": {},
        "requirements_preserved": True,
        "capability_strategy": {"mode": "native_supported"},
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
            messages = payload.get("messages") or [{}]
            prompt = "\n".join(str(item.get("content", "")) for item in messages if isinstance(item, dict))
        except Exception:
            prompt = ""
        data = _json_response(_completion_for(prompt))
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
    backup_dir = Path(tempfile.mkdtemp(prefix="studio_v65_uat_config_"))
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

def _stop_process_tree(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

def _vite_dev_command(port: int) -> tuple[list[str], Path]:
    bin_name = "vite.cmd" if os.name == "nt" else "vite"
    local_vite = ROOT / "studio" / "frontend" / "node_modules" / ".bin" / bin_name
    if local_vite.exists():
        return [str(local_vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"], ROOT / "studio" / "frontend"
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    return [npm, "run", "dev", "--prefix", "studio/frontend", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"], ROOT


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


def _request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout_s: float = 30.0) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body}
        return exc.code, parsed


def _poll_state(api_base: str, predicate, timeout_s: float = 120.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    state: dict[str, Any] = {}
    while time.time() < deadline:
        _, state = _request_json(f"{api_base}/api/runs/current_state", timeout_s=10)
        if predicate(state):
            return state
        time.sleep(0.5)
    return state


def _edge_path() -> Path | None:
    for path in EDGE_CANDIDATES:
        if path.is_file():
            return path
    return None


def _screenshot(frontend_url: str, output_path: Path) -> bool:
    edge = _edge_path()
    if not edge:
        return False
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
    result = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=45)
    if result.returncode != 0:
        output_path.with_suffix(".stderr.txt").write_text(result.stderr + "\n" + result.stdout, encoding="utf-8")
    return output_path.is_file()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _count_council_layers(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not path.is_file():
        return counts
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        layer = str(event.get("layer") or "")
        if event.get("event_type") == "agent1_council_node" and event.get("status") in {"pass", "conflict", "fail"}:
            counts[layer] = counts.get(layer, 0) + 1
    return counts


def _merge_layer_counts(*items: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _artifact_summary(output_dir: Path) -> dict[str, Any]:
    reports = output_dir / "reports"
    agent1 = reports / "agent1"
    traces = reports / "traces"
    conflict = _read_json(agent1 / "agent1_conflict_matrix.json")
    health = _read_json(traces / "trace_health_report.json")
    invariants = _read_json(traces / "trace_invariant_report.json")
    trace_files = sorted(path.name for path in traces.glob("*") if path.is_file()) if traces.is_dir() else []
    council_layer_counts = _merge_layer_counts(
        _count_council_layers(traces / "agent1_council_trace.jsonl"),
        _count_council_layers(traces / "agent1_guardrail_trace.jsonl"),
    )
    secret_hits = []
    if reports.is_dir():
        for path in reports.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "uat-local-key" in text or re.search(r"\bsk-[A-Za-z0-9_\-]{20,}\b", text) or re.search(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", text, re.I):
                    secret_hits.append(str(path))
    return {
        "architecture_plan_exists": (reports / "architecture_plan.md").is_file(),
        "clarification_exists": (reports / "agent1_requirement_clarification.md").is_file(),
        "intake_report_exists": (agent1 / "agent1_intake_router_report.json").is_file(),
        "conflict_matrix_exists": bool(conflict),
        "critical_conflicts": len(conflict.get("critical_conflicts") or []) if conflict else None,
        "noncritical_conflicts": len(conflict.get("noncritical_conflicts") or []) if conflict else None,
        "trace_health_exists": bool(health),
        "trace_health_pass": health.get("pass") if health else None,
        "trace_health_score": health.get("score") if health else None,
        "trace_invariant_pass": invariants.get("pass") if invariants else None,
        "trace_files": trace_files,
        "trace_files_required_present": all(name in trace_files for name in TRACE_FILES_REQUIRED),
        "council_layer_counts": council_layer_counts,
        "agent2_dir_exists": (output_dir / "rtl").exists(),
        "secret_hit_count": len(secret_hits),
        "secret_hits": secret_hits[:10],
    }


def _case_pass(summary: dict[str, Any]) -> bool:
    if summary.get("status_code") != 200 or summary.get("actual_action") != summary.get("expected_action"):
        return False
    artifacts = summary.get("artifacts", {})
    if artifacts.get("secret_hit_count") != 0:
        return False
    if artifacts.get("trace_health_pass") is not True or float(artifacts.get("trace_health_score") or 0) < 95:
        return False
    if artifacts.get("trace_invariant_pass") is not True:
        return False
    required_trace_files = TRACE_FILES_REQUIRED_BY_ACTION.get(str(summary.get("expected_action")), TRACE_FILES_REQUIRED)
    if not all(name in (artifacts.get("trace_files") or []) for name in required_trace_files):
        return False
    if summary.get("expected_action") == "PLAN_REVIEW":
        layers = artifacts.get("council_layer_counts", {})
        return bool(
            artifacts.get("architecture_plan_exists")
            and artifacts.get("critical_conflicts") == 0
            and layers.get("leaf", 0) >= 24
            and layers.get("middle", 0) >= 7
            and layers.get("principal", 0) >= 1
            and layers.get("guardrail", 0) >= 1
        )
    return bool(artifacts.get("clarification_exists"))


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
    report: dict[str, Any] = {
        "schema_version": "studio.v65.tracking_uat_report.v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "api_base": api_base,
        "frontend_url": frontend_url,
        "fake_codex_endpoint": fake_endpoint,
        "cases": [],
    }
    backend_proc: subprocess.Popen[str] | None = None
    frontend_proc: subprocess.Popen[str] | None = None
    with fake_codex_server(fake_port), backed_up_configs(fake_endpoint, output_root, checkpoint_db):
        backend_proc = _start_process([str(PYTHON), "-m", "uvicorn", "studio.backend.server:app", "--host", "127.0.0.1", "--port", str(backend_port)], ROOT, env, evidence_dir / "backend.log")
        frontend_cmd, frontend_cwd = _vite_dev_command(frontend_port)
        frontend_proc = _start_process(frontend_cmd, frontend_cwd, frontend_env, evidence_dir / "frontend.log")
        try:
            _wait_url(f"{api_base}/api/health")
            _wait_url(frontend_url)
            status, settings = _request_json(f"{api_base}/api/settings")
            test_status, test_body = _request_json(
                f"{api_base}/api/settings/test-connection",
                "POST",
                {"endpoint": settings.get("endpoint"), "model": settings.get("model"), "apiKeyRef": settings.get("activeKeyRef", "owner")},
            )
            report["settings_test"] = {"status": test_status, "body": test_body, "pass": test_status == 200 and test_body.get("ok") is True}
            cases = [
                ("pure_hi", "hi", "REQUIREMENT_CLARIFICATION"),
                ("identity_question", "Hi, ban la ai", "REQUIREMENT_CLARIFICATION"),
                ("age_question", "ban may tuoi", "REQUIREMENT_CLARIFICATION"),
                ("bus_contradiction", "Generate an APB only UART controller but also use AXI only bus", "REQUIREMENT_CLARIFICATION"),
                ("minimum_cpu_apb_uart", "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral", "PLAN_REVIEW"),
                ("mixed_identity_uart", "ban la ai, tao UART APB controller 50MHz", "PLAN_REVIEW"),
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
                    "startPolicy": "fresh",
                }
                status, body = _request_json(f"{api_base}/api/runs/start", "POST", payload)
                state = _poll_state(api_base, lambda item: bool(item.get("pause")) or item.get("status") in {"failed", "done", "stopped"}, timeout_s=180.0)
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
                }
                summary["pass"] = _case_pass(summary)
                report["cases"].append(summary)
                if case_id == "minimum_cpu_apb_uart" and summary["pass"] and state.get("run_id"):
                    last_event_id = int(state.get("last_event_id") or 0)
                    last_pause_event_id = int((state.get("pause") or {}).get("event_id") or 0)
                    resume_payload = {"notes": "ok", "resume_action": action, "planning_mode": "normal", "apiKeyRef": "owner"}
                    r_status, r_body = _request_json(f"{api_base}/api/runs/{state['run_id']}/resume", "POST", resume_payload)
                    resumed_state = _poll_state(
                        api_base,
                        lambda item: int(item.get("last_event_id") or 0) > last_event_id
                        and (
                            int((item.get("pause") or {}).get("event_id") or 0) > last_pause_event_id
                            or item.get("status") in {"done", "failed", "stopped"}
                        ),
                        timeout_s=180.0,
                    )
                    resume_summary = {
                        "case": "minimum_cpu_apb_uart_resume_ok",
                        "status_code": r_status,
                        "body": r_body,
                        "state_status": resumed_state.get("status"),
                        "actual_action": (resumed_state.get("pause") or {}).get("action_required"),
                        "artifacts": _artifact_summary(output_dir),
                        "pass": r_status == 200 and resumed_state.get("status") in {"paused", "done", "stopped"} and _artifact_summary(output_dir).get("secret_hit_count") == 0,
                    }
                    (case_dir / "resume_response.json").write_text(json.dumps({"status": r_status, "body": r_body}, indent=2, sort_keys=True), encoding="utf-8")
                    (case_dir / "resumed_state.json").write_text(json.dumps(resumed_state, indent=2, sort_keys=True), encoding="utf-8")
                    report["cases"].append(resume_summary)
            repeat_payload = {
                "requirement": "Generate a 32-bit CPU architecture using an APB bus, with UART as the external peripheral",
                "project_name": "minimum_cpu_apb_uart",
                "output_dir": str(output_root / "minimum_cpu_apb_uart"),
                "planning_mode": "normal",
                "checkpoint_db": str(checkpoint_db),
                "apiKeyRef": "owner",
            }
            repeat_status, repeat_body = _request_json(f"{api_base}/api/runs/start", "POST", repeat_payload)
            report["cases"].append(
                {
                    "case": "output_conflict_guard",
                    "expected_status": 409,
                    "actual_status": repeat_status,
                    "actual_detail": repeat_body.get("detail"),
                    "pass": repeat_status == 409 and "OUTPUT_EXISTS" in str(repeat_body.get("detail")),
                }
            )
        finally:
            for proc in (frontend_proc, backend_proc):
                _stop_process_tree(proc)
    report["pass"] = bool(report.get("settings_test", {}).get("pass")) and all(bool(item.get("pass")) for item in report["cases"])
    (evidence_dir / "uat_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", default=str(ROOT / "outputs" / "uat_evidence" / f"studio_v65_tracking_{datetime.now().strftime('%Y%m%d_%H%M%S')}"))
    args = parser.parse_args(argv)
    evidence_dir = Path(args.evidence_dir)
    report = run_uat(evidence_dir)
    print(
        json.dumps(
            {
                "pass": report["pass"],
                "evidence_dir": str(evidence_dir),
                "settings_test": report.get("settings_test", {}).get("pass"),
                "cases": [
                    {
                        "case": item.get("case"),
                        "pass": item.get("pass"),
                        "expected_action": item.get("expected_action"),
                        "actual_action": item.get("actual_action"),
                        "actual_status": item.get("actual_status"),
                    }
                    for item in report["cases"]
                ],
            },
            indent=2,
        )
    )
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
