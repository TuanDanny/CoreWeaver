from __future__ import annotations

from coreweaver.debug.issues import DebugIssueRecord
from coreweaver.harness.secret_scan import scan_text_for_secrets

from .base import HookContext
from .results import HookResult, HookStatus


class _NamedHook:
    def __init__(self, name: str, fn) -> None:
        self.name = name
        self._fn = fn

    async def __call__(self, context: HookContext) -> HookResult:
        return await self._fn(context)


async def _secret_scan(context: HookContext) -> HookResult:
    findings = scan_text_for_secrets(str(context.payload))
    if findings:
        return HookResult(
            status=HookStatus.BLOCK,
            hook_name="secret_scan",
            source="security",
            reason="secret-like payload blocked",
            debug_issue=DebugIssueRecord(
                severity="blocker",
                source="hook.secret_scan",
                code="secret_payload_blocked",
                message="Secret-like payload was blocked before forwarding.",
            ),
        )
    return HookResult.continue_("secret_scan")


async def _trace_debug(context: HookContext) -> HookResult:
    return HookResult(status=HookStatus.CONTINUE, hook_name="trace_debug", source="debug", reason="trace observed")


async def _budget(context: HookContext) -> HookResult:
    budget_left = context.metadata.get("budget_left")
    if isinstance(budget_left, (int, float)) and budget_left < 0:
        return HookResult(status=HookStatus.REQUIRE_HITL, hook_name="budget", source="safety", reason="budget exceeded")
    return HookResult.continue_("budget")


async def _invariant(context: HookContext) -> HookResult:
    return HookResult.continue_("invariant")


secret_scan_hook = _NamedHook("secret_scan", _secret_scan)
trace_debug_hook = _NamedHook("trace_debug", _trace_debug)
budget_hook = _NamedHook("budget", _budget)
invariant_hook = _NamedHook("invariant", _invariant)
