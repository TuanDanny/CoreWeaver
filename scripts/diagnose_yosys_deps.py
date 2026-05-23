"""Diagnose Windows DLL/runtime issues for OSS CAD Suite yosys.exe.

The script prefers Microsoft `dumpbin /dependents` when available, then falls
back to a lightweight PE import-table parser and PATH search. It also runs a
few smoke commands with OSS CAD Suite's bin directory prepended to PATH.
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yosys", default=shutil.which("yosys") or r"D:\APP\oss-cad-suite\bin\yosys.exe")
    args = parser.parse_args()

    yosys = Path(args.yosys).resolve()
    bin_dir = yosys.parent
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    print(f"YOSYS={yosys}")
    print(f"EXISTS={yosys.exists()}")
    print(f"BIN_DIR={bin_dir}")
    print(f"DUMPBIN={shutil.which('dumpbin')}")

    deps = dumpbin_deps(yosys) or pe_import_dlls(yosys)
    print("DEPENDENTS=" + (", ".join(deps) if deps else "<none/unknown>"))
    missing = [dep for dep in deps if not find_dll(dep, bin_dir, env.get("PATH", ""))]
    print("MISSING=" + (", ".join(missing) if missing else "<none detected by PATH scan>"))

    for cmd in ([str(yosys), "-V"], [str(yosys), "-p", "help"], [str(bin_dir / "sby.exe"), "--version"]):
        run_probe(cmd, env)

    if missing:
        print("FIX_HINT=Add the directory containing the missing DLLs to PATH, reinstall OSS CAD Suite, or copy the matching DLLs into the OSS CAD Suite bin directory.")
        return 2
    print("FIX_HINT=No missing import DLL found. Exit code 0xC0000005 usually means a crashing DLL/runtime conflict; try running with OSS bin first in PATH, reinstall OSS CAD Suite, or use WSL/Linux OSS CAD Suite.")
    return 0


def dumpbin_deps(exe: Path) -> list[str]:
    dumpbin = shutil.which("dumpbin")
    if not dumpbin:
        return []
    proc = subprocess.run([dumpbin, "/dependents", str(exe)], text=True, capture_output=True, check=False)
    deps = []
    for line in proc.stdout.splitlines():
        item = line.strip()
        if item.lower().endswith(".dll"):
            deps.append(item)
    return sorted(set(deps), key=str.lower)


def pe_import_dlls(exe: Path) -> list[str]:
    data = exe.read_bytes()
    if data[:2] != b"MZ":
        return []
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        return []
    sections_count = struct.unpack_from("<H", data, pe_off + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe_off + 20)[0]
    opt_off = pe_off + 24
    magic = struct.unpack_from("<H", data, opt_off)[0]
    data_dir_off = opt_off + (112 if magic == 0x20B else 96)
    import_rva, _ = struct.unpack_from("<II", data, data_dir_off + 8)
    sec_off = opt_off + opt_size
    sections = []
    for i in range(sections_count):
        off = sec_off + i * 40
        virt_size, virt_addr, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((virt_addr, max(virt_size, raw_size), raw_ptr))

    def rva_to_off(rva: int) -> int | None:
        for virt_addr, size, raw_ptr in sections:
            if virt_addr <= rva < virt_addr + size:
                return raw_ptr + (rva - virt_addr)
        return None

    imp_off = rva_to_off(import_rva)
    if imp_off is None:
        return []
    deps = []
    while True:
        desc = struct.unpack_from("<IIIII", data, imp_off)
        if desc == (0, 0, 0, 0, 0):
            break
        name_off = rva_to_off(desc[3])
        if name_off is not None:
            deps.append(read_c_string(data, name_off))
        imp_off += 20
    return sorted(set(deps), key=str.lower)


def read_c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    return data[offset:end].decode("ascii", errors="replace")


def find_dll(name: str, bin_dir: Path, path: str) -> Path | None:
    candidates = [bin_dir, *[Path(item) for item in path.split(os.pathsep) if item]]
    for directory in candidates:
        dll = directory / name
        if dll.exists():
            return dll
    return None


def run_probe(cmd: list[str], env: dict[str, str]) -> None:
    print("RUN=" + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, env=env, text=True, capture_output=True, check=False, timeout=120)
    except Exception as exc:  # pragma: no cover - diagnostic script
        print(f"ERROR={exc}")
        return
    print(f"RETURNCODE={proc.returncode}")
    if proc.stdout.strip():
        print("STDOUT_TAIL=" + " | ".join(proc.stdout.splitlines()[-5:]))
    if proc.stderr.strip():
        print("STDERR_TAIL=" + " | ".join(proc.stderr.splitlines()[-5:]))


if __name__ == "__main__":
    raise SystemExit(main())