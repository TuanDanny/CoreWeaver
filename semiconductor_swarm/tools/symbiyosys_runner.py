"""Real SymbiYosys runner and parser for Agent 5."""
from __future__ import annotations

import re
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SbyRunResult:
    block: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "command": self.command,
            "returncode": self.returncode,
            "stdout_tail": self.stdout.splitlines()[-80:],
            "stderr_tail": self.stderr.splitlines()[-80:],
            "result": self.result,
        }


def parse_sby_result_text(result_text: str, block_name: str = "unknown") -> dict[str, Any]:
    upper = result_text.upper()
    status = "UNKNOWN"
    if re.search(r"\b(PASS|PASSED|STATUS:\s*PASSED)\b", upper):
        status = "PASS"
    if re.search(r"\b(FAIL|FAILED|STATUS:\s*FAILED|ASSERT FAIL)\b", upper):
        status = "FAIL"
    lines = [line.strip() for line in result_text.splitlines() if line.strip()]
    cex = [line for line in lines if re.search(r"counterexample|trace|engine_\d+|failed|assert|cex|vcd", line, re.I)]
    failing_property = ""
    for line in cex:
        match = re.search(r"(assert[^\s:;]*|\$assert[^\s:;]*|fv_[\w.:-]+)", line, re.I)
        if match:
            failing_property = match.group(1)
            break
    return {
        "block": block_name,
        "status": status,
        "pass": status == "PASS",
        "solver": "z3" if "Z3" in upper or "SMTBMC" in upper else "unknown",
        "failing_property": failing_property,
        "counterexample": "\n".join(cex[-40:]),
        "summary_tail": "\n".join(lines[-40:]),
    }


def run_symbiyosys(block_name: str, formal_dir: str | Path = "formal", *, sby: str = "sby", require_sby: bool = True) -> SbyRunResult:
    if require_sby and shutil.which(sby) is None:
        raise FileNotFoundError(f"Cannot find {sby!r}. Install OSS CAD Suite and add its bin directory to PATH.")
    formal_path = Path(formal_dir)
    cmd = [sby, "-f", f"{block_name}.sby"]
    proc = subprocess.run(cmd, cwd=formal_path, env=_oss_cad_env(sby), text=True, capture_output=True, check=False, timeout=300)
    text = proc.stdout + "\n" + proc.stderr
    return SbyRunResult(block_name, cmd, proc.returncode, proc.stdout, proc.stderr, parse_sby_result_text(text, block_name))


def _oss_cad_env(sby: str) -> dict[str, str]:
    """Put OSS CAD Suite bin/lib first so child yosys can load bundled DLLs."""
    env = os.environ.copy()
    resolved = shutil.which(sby)
    if not resolved:
        return env
    bin_dir = Path(resolved).resolve().parent
    root = bin_dir.parent
    prefixes = [str(bin_dir), str(root / "lib")]
    env["PATH"] = os.pathsep.join(prefixes + [env.get("PATH", "")])
    return env