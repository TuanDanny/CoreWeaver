"""Process-local structured runtime event sink used by the app runner."""
from __future__ import annotations

from typing import Any, Callable

RuntimeSink = Callable[[dict[str, Any]], None]
_sink: RuntimeSink | None = None


def set_runtime_event_sink(sink: RuntimeSink | None) -> None:
    global _sink
    _sink = sink


def emit_runtime_event(event: dict[str, Any]) -> None:
    if _sink is not None:
        _sink(event)
