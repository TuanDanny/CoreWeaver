"""Print JSON availability report for optional real EDA toolchain."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semiconductor_swarm.tools.tool_detection import detect_real_tools


def main() -> None:
    print(json.dumps(detect_real_tools(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()