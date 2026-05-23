"""Local-only secret administration for Studio credentials."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from studio.backend import config

def set_owner_key(api_key: str | None = None, *, config_path: Path | None = None) -> Path:
    """Update the owner key without echoing or returning the secret."""
    target = config_path or config.CODEX_CONFIG_PATH
    key = api_key if api_key is not None else getpass.getpass("Owner API key: ")
    if not key or not key.strip():
        raise ValueError("Owner API key cannot be empty")
    current = config._read_json(target)
    next_data = {
        "base_url": current.get("base_url") or "http://localhost:20128/v1",
        "model": current.get("model") or "cx/gpt-5.5",
        "api_key": key.strip(),
    }
    config._write_json(target, next_data)
    return target

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SWARM AI STUDIO local secret admin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("set-owner-key", help="Update the server-side owner API key")
    args = parser.parse_args(argv)
    if args.command == "set-owner-key":
        path = set_owner_key()
        print(f"Owner credential updated at {path}")
        return 0
    parser.error("unknown command")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
