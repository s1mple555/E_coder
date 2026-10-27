"""Default PreToolUse permission hook; UI approval remains the trust boundary."""
import asyncio
import time

from .store import uid
from .tools import SPECS


async def permission_hook(context):
    if context.allowed_tools is not None and context.name not in context.allowed_tools:
        return f"子 Agent 不允许使用工具: {context.name}"
    try:
        context.args = context.tools.validate(context.name, context.args)
        if context.name in {"list_files", "read_file", "search_code"}:
            context.tools.path(context.args["path"], read_only=context.name == "read_file")
        if SPECS[context.name][2] != "approval":
            return None
        if context.runtime.settings.permission_mode == "full" and context.name == "run_command":
            context.args["execution_mode"] = "host"
        context.prepared = context.tools.preview(context.name, context.args)
    except ValueError as error:
        return str(error)[:1500]
    runtime, session, run = context.runtime, context.session, context.run
    if runtime.settings.permission_mode == "full":
        runtime.emit(session, run, "permission_auto_allow", call_id=context.call_id,
                     name=context.name, permission_mode="full", arguments=context.args,
                     preview={k: v for k, v in context.prepared.items() if k not in {"before", "after"}})
        return None
    approval_id = uid()
    timeout = runtime.approval_timeout
    future = asyncio.get_running_loop().create_future()
    public = {"approval_id": approval_id, "call_id": context.call_id,
              "name": context.name, "arguments": context.args,
              "preview": {k: v for k, v in context.prepared.items() if k not in {"before", "after"}},
              "expires_at": time.time() + timeout}
    run.approvals[approval_id] = {**public, "future": future}
    try:
        runtime.emit(session, run, "approval_request", **public)
        try:
            allow = await asyncio.wait_for(future, timeout)
        except TimeoutError:
            runtime.emit(session, run, "approval_result", approval_id=approval_id, allowed=False, reason="timeout")
            return "审批超时，未执行"
        except asyncio.CancelledError:
            runtime.emit(session, run, "approval_result", approval_id=approval_id, allowed=False, reason="cancelled")
            raise
        runtime.emit(session, run, "approval_result", approval_id=approval_id, allowed=allow)
        if not allow:
            return "用户拒绝了此次操作，未执行"
        return None
    finally:
        run.approvals.pop(approval_id, None)
        if not future.done():
            future.cancel()
