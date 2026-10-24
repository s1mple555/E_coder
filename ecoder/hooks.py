"""Per-runtime lifecycle hooks, modeled after learn-claude-code/s04_hooks.

Callbacks run serially, ordered by ascending priority then registration order.
None continues; the first string short-circuits the event. Only trusted Python
code registers callbacks: skill text and model tool calls cannot register hooks.
"""
from dataclasses import dataclass
import inspect
from typing import Any, Callable


EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


class HookError(ValueError):
    pass


@dataclass
class AgentHookContext:
    runtime: Any
    session: str
    run: Any
    messages: list
    prompt: str | None = None


@dataclass
class ToolHookContext:
    runtime: Any
    session: str
    run: Any
    tools: Any
    name: str
    call_id: str
    args: dict
    allowed_tools: frozenset | None = None
    prepared: dict | None = None
    result: Any = None


class Hooks:
    def __init__(self, reporter: Callable | None = None):
        self._callbacks = {event: [] for event in EVENTS}
        self._reporter = reporter

    def register_hook(self, event, callback, *, priority=0):
        if event not in self._callbacks:
            raise ValueError(f"未知 Hook 事件: {event}")
        if not callable(callback):
            raise TypeError("Hook 必须可调用")
        self._callbacks[event].append((priority, callback))

    async def trigger_hooks(self, event, context):
        if event not in self._callbacks:
            raise ValueError(f"未知 Hook 事件: {event}")
        # Snapshot: registration during dispatch affects the next event only.
        for _, callback in sorted(self._callbacks[event], key=lambda item: item[0]):
            name = getattr(callback, "__name__", type(callback).__name__)
            try:
                result = callback(context)
                if inspect.isawaitable(result):
                    result = await result
                if result is not None and (not isinstance(result, str) or not result.strip()):
                    raise TypeError("Hook 返回值必须是非空字符串或 None")
            except Exception as error:
                if self._reporter:
                    self._reporter(event, name, "failed", context)
                # Callback exception text can contain private tool data.
                raise HookError(f"{event} Hook {name} 执行失败（{type(error).__name__}）") from error
            if self._reporter:
                status = "passed" if result is None else "returned"
                self._reporter(event, name, status, context)
            if result is not None:
                return result
        return None
