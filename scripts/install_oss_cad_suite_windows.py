"""Download and install OSS CAD Suite for Windows.

Usage:
  python scripts/install_oss_cad_suite_windows.py --install-dir C:\oss-cad-suite --user-path

The script downloads the latest Windows x64 release archive from GitHub,
extracts it, and can append the `bin` directory to the current user's PATH.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_URL = "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-windows-x64.zip"


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, target.open("wb") as out:
        shutil.copyfileobj(response, out)


def _set_user_path(bin_dir: Path) -> None:
    current = os.environ.get("PATH", "")
    parts = [Path(part).resolve() for part in current.split(os.pathsep) if part]
    if bin_dir.resolve() in parts:
        return
    new_path = current + os.pathsep + str(bin_dir) if current else str(bin_dir)
    subprocess.run(["setx", "PATH", new_path], check=True)


def install_oss_cad_suite(install_dir: Path, *, url: str = DEFAULT_URL, user_path: bool = False) -> Path:
    archive = install_dir.parent / "oss-cad-suite-windows-x64.zip"
    _download(url, archive)
    if install_dir.exists():
        shutil.rmtree(install_dir)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(install_dir.parent)
    extracted = install_dir.parent / "oss-cad-suite"
    if extracted != install_dir:
        if install_dir.exists():
            shutil.rmtree(install_dir)
        extracted.rename(install_dir)
    bin_dir = install_dir / "bin"
    if user_path:
        _set_user_path(bin_dir)
    return bin_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Install OSS CAD Suite for Windows")
    parser.add_argument("--install-dir", default=r"C:\oss-cad-suite", type=Path)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--user-path", action="store_true", help="append install_dir/bin to user PATH via setx")
    args = parser.parse_args()
    bin_dir = install_oss_cad_suite(args.install_dir, url=args.url, user_path=args.user_path)
    print(f"OSS CAD Suite bin: {bin_dir}")
    print("Open a new terminal, then verify with: sby --version && z3 --version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())