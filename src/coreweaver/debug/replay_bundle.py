from __future__ import annotations

from pydantic import Field

from coreweaver.events.core_event import CoreEvent
from coreweaver.framework_types import StrictCoreModel
from coreweaver.messages.core_message import CoreMessage

from .invariants import ContextSummary


class ReplayBundle(StrictCoreModel):
    run_id: str
    messages: tuple[CoreMessage, ...] = ()
    events: tuple[CoreEvent, ...] = ()
    context_summary: ContextSummary = Field(default_factory=lambda: ContextSummary(task_overview="framework skeleton"))

    def event_order(self) -> tuple[str, ...]:
        return tuple(event.span_id for event in self.events)
