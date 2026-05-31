from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any, Callable


class ExecutorPolicy:
    def __init__(self, *, max_cpu_workers: int = 2, max_io_workers: int = 4) -> None:
        self._cpu_pool = ProcessPoolExecutor(max_workers=max_cpu_workers)
        self._io_pool = ThreadPoolExecutor(max_workers=max_io_workers)

    async def run_cpu(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._cpu_pool, fn, *args)

    async def run_io(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._io_pool, fn, *args)

    def shutdown(self) -> None:
        self._cpu_pool.shutdown(cancel_futures=True)
        self._io_pool.shutdown(cancel_futures=True)
