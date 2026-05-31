from __future__ import annotations

from collections.abc import Iterable

from coreweaver.debug.issues import DebugIssueRecord

from .base import Hook, HookContext
from .results import HookResult, HookStatus


class HookChain:
    def __init__(self, hooks: Iterable[Hook]) -> None:
        self.hooks = tuple(hooks)

    async def run(self, context: HookContext) -> tuple[HookResult, ...]:
        results: list[HookResult] = []
        current = context
        for hook in self.hooks:
            try:
                result = await hook(current)
            except Exception as exc:
                result = HookResult(
                    status=HookStatus.BLOCK,
                    hook_name=getattr(hook, "name", hook.__class__.__name__),
                    source="hook_chain",
                    reason=f"hook raised unexpected exception: {exc}",
                    debug_issue=DebugIssueRecord(
                        severity="error",
                        source="hook_chain",
                        code="hook_exception",
                        message=str(exc),
                    ),
                )
            results.append(result)
            if result.status == HookStatus.REPLACE_PAYLOAD:
                current = current.model_copy(update={"payload": result.replacement_payload})
            if result.terminal:
                break
        return tuple(results)
