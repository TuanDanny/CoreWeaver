"""Run Agent 2 test profiles: demo, dev, strict, nightly."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


PROFILES = {
    "demo": ["tests/test_agent2.py", "tests/test_agent2_v4_quality_score.py", "tests/test_agent2_v4_compile_order.py"],
    "dev": ["tests/test_agent2.py", "tests/test_agent2_v4_negative_fixtures.py", "tests/test_agent2_v4_upf_consistency.py", "tests/test_agent2_v4_lec_repair.py"],
    "strict": ["tests/test_agent2_v4_strict_eda.py", "tests/test_agent2_v4_toolchain_reproducibility.py", "tests/test_real_tool_detection.py"],
    "nightly": ["tests", "-m", "not real_tools"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=PROFILES)
    args = parser.parse_args()
    env = os.environ.copy()
    env["SWARM_MODE"] = "nightly_real_tools" if args.profile == "nightly" else args.profile
    cmd = [sys.executable, "-m", "pytest", *PROFILES[args.profile]]
    print(" ".join(cmd))
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    raise SystemExit(main())