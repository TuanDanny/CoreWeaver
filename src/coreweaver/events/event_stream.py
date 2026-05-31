from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .core_event import CoreEvent


class AsyncEventStream:
    """Async append-only event stream with replayable in-memory history."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[CoreEvent | None] = asyncio.Queue()
        self._history: list[CoreEvent] = []
        self._closed = False

    @property
    def history(self) -> tuple[CoreEvent, ...]:
        return tuple(self._history)

    async def emit(self, event: CoreEvent) -> None:
        if self._closed:
            raise RuntimeError("event stream is closed")
        self._history.append(event)
        await self._queue.put(event)

    async def close(self) -> None:
        self._closed = True
        await self._queue.put(None)

    async def __aiter__(self) -> AsyncIterator[CoreEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event
