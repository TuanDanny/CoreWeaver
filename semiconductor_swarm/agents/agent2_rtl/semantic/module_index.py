"""Lightweight semantic SystemVerilog module index.

Regex/state-machine parser intentionally small: enough for generated RTL
contracts, not a full SystemVerilog compiler.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RTLModuleIndexEntry:
    module_name: str
    filename: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    ports: list[dict[str, Any]] = field(default_factory=list)
    instances: list[dict[str, Any]] = field(default_factory=list)
    always_blocks: list[dict[str, Any]] = field(default_factory=list)
    assigns: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_rtl_module_index(files: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[RTLModuleIndexEntry] = []
    for file in files:
        if file.get("language") != "systemverilog":
            continue
        content = str(file.get("content", ""))
        filename = str(file.get("filename", ""))
        entries.extend(_index_file(filename, content))
    dependencies = _dependency_edges(entries)
    duplicates = _duplicate_modules(entries)
    unresolved = _unresolved_instances(entries)
    return {
        "schema_version": "agent2.semantic_module_index.v1",
        "artifact_aliases": ["rtl_module_index.json", "semantic_module_index.json"],
        "module_count": len(entries),
        "modules": [entry.as_dict() for entry in entries],
        "dependency_edges": dependencies,
        "duplicate_modules": duplicates,
        "unresolved_instances": unresolved,
    }


def _index_file(filename: str, content: str) -> list[RTLModuleIndexEntry]:
    results: list[RTLModuleIndexEntry] = []
    for match in re.finditer(r"\bmodule\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b(?P<body>.*?)(?=\bendmodule\b)", content, re.S):
        name = match.group("name")
        body = match.group("body")
        header = body.split(");", 1)[0]
        results.append(
            RTLModuleIndexEntry(
                module_name=name,
                filename=filename,
                parameters=_parameters(header),
                ports=_ports(header),
                instances=_instances(body),
                always_blocks=_always_blocks(body),
                assigns=_assigns(body),
                content=body,
            )
        )
    return results


def _parameters(text: str) -> list[dict[str, Any]]:
    return [{"name": m.group("name"), "default": (m.group("default") or "").strip()} for m in re.finditer(r"parameter\s+(?:int|logic|bit)?\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*(?P<default>[^,\)]+))?", text)]


def _ports(text: str) -> list[dict[str, Any]]:
    ports = []
    pattern = re.compile(r"\b(?P<dir>input|output|inout)\s+(?P<type>logic|wire|reg)?\s*(?P<width>\[[^\]]+\])?\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b\s*(?=,|\)|//|$)", re.M)
    for m in pattern.finditer(text):
        ports.append({"name": m.group("name"), "direction": m.group("dir"), "type": m.group("type") or "", "width": m.group("width") or "1"})
    return ports


def _instances(text: str) -> list[dict[str, Any]]:
    instances = []
    pattern = re.compile(r"^\s*(?P<module>[A-Za-z_][A-Za-z0-9_]*)\s+(?:#\s*\([^;]*?\)\s*)?(?P<name>u_[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M | re.S)
    for m in pattern.finditer(text):
        if m.group("module") in {"module", "assign", "always_ff", "always_comb"}:
            continue
        instances.append({"module": m.group("module"), "instance": m.group("name")})
    return instances


def _always_blocks(text: str) -> list[dict[str, Any]]:
    return [{"kind": m.group("kind"), "sensitivity": (m.group("sens") or "").strip()} for m in re.finditer(r"\b(?P<kind>always_ff|always_comb|always_latch|always)\s*(?P<sens>@\([^\)]*\))?", text)]


def _assigns(text: str) -> list[dict[str, Any]]:
    return [{"lhs": m.group("lhs").strip(), "rhs": m.group("rhs").strip()} for m in re.finditer(r"\bassign\s+(?P<lhs>[^=;]+)=\s*(?P<rhs>[^;]+);", text)]


def _dependency_edges(entries: list[RTLModuleIndexEntry]) -> list[dict[str, str]]:
    known = {entry.module_name for entry in entries}
    edges = []
    for entry in entries:
        for instance in entry.instances:
            target = instance["module"]
            if target in known:
                edges.append({"from": entry.module_name, "to": target, "instance": instance["instance"]})
    return edges


def _duplicate_modules(entries: list[RTLModuleIndexEntry]) -> list[dict[str, Any]]:
    by_name: dict[str, list[str]] = {}
    for entry in entries:
        by_name.setdefault(entry.module_name, []).append(entry.filename)
    return [{"module": name, "files": files, "count": len(files)} for name, files in sorted(by_name.items()) if len(files) > 1]


def _unresolved_instances(entries: list[RTLModuleIndexEntry]) -> list[dict[str, str]]:
    known = {entry.module_name for entry in entries}
    unresolved: list[dict[str, str]] = []
    for entry in entries:
        for instance in entry.instances:
            target = str(instance["module"])
            if target not in known:
                unresolved.append({"from": entry.module_name, "module": target, "instance": str(instance["instance"]), "filename": entry.filename})
    return unresolved