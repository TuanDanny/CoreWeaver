"""Install Python DV dependencies for real Cocotb/Verilator runs."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements-dv.txt"

def main() -> int:
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQ)]
    return subprocess.run(cmd, check=False).returncode

if __name__ == "__main__":
    raise SystemExit(main())
