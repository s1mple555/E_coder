"""Opt-in live API test: .venv/Scripts/python.exe tests/live_subagent_smoke.py.

Uses configured credentials without displaying them. Sends only synthetic test
files; stores all test messages and writes in a temporary directory. Consumes
model tokens. Automatically approves only the exact expected child file write.
"""
import asyncio
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecoder.config import Settings
from ecoder.runtime import Runtime
from ecoder.skills import Skills
from ecoder.store import Store
from ecoder.tools import Tools


async def smoke():
    configured = Settings.load()
    if not configured.api_key:
        raise ValueError("未配置 API Key")
    with tempfile.TemporaryDirectory(prefix="ecoder-subagent-smoke-") as folder:
        root = Path(folder)
        settings = replace(configured, root=root, workspace=root / "workspace", max_steps=12)
        store = Store(root / "state.db")
        # Deliberately empty skills: this test needs no user documents or scripts.
        skills = Skills(root / "skills")
        tools = Tools(settings.workspace, store, skills)
        runtime = Runtime(settings, store, tools, skills)
        marker = "SUBAGENT_VERIFIED_" + uuid.uuid4().hex[:12]
        (tools.root / "probe.txt").write_text(marker, encoding="utf-8")
        session = store.create_session("live sub-agent smoke test")["id"]
        runtime.start(session,
            "这是子 Agent 集成测试。你必须先调用 sub_agent 委派以下完整任务，不要自己读写文件："
            "读取当前目录 probe.txt，将读取到的完整文本原样写入 result.txt，再读回验证。"
            "子 Agent 的最终结论必须包含完整文件内容和验证结果。"
            "收到子 Agent 结果后，主 Agent 的最终回答也必须包含完整文件内容和验证结果。不要执行命令。")
        worker = runtime.active[session].task
        approved = set()
        started = time.monotonic()
        try:
            while not worker.done():
                if time.monotonic() - started > 300:
                    raise ValueError("真实 API 测试超过 300 秒")
                for item in runtime.pending(session):
                    if item["approval_id"] in approved:
                        continue
                    child = any(event["type"] == "approval_request" and event.get("subagent_id") and event["approval_id"] == item["approval_id"] for event in store.events(session))
                    allow = (child and item["name"] == "write_file"
                             and tools.path(item["arguments"]["path"]) == tools.root / "result.txt"
                             and item["arguments"]["content"] == marker)
                    runtime.approve(session, item["approval_id"], bool(allow))
                    approved.add(item["approval_id"])
                    if not allow:
                        raise ValueError("模型请求了测试范围外的修改，已拒绝")
                await asyncio.sleep(0.1)
            await worker
            events, history = store.events(session), store.messages(session)
            assert events[-1]["status"] == "completed", "主循环未正常完成"
            assert any(event["type"] == "subagent_end" and event["status"] == "completed" for event in events), "子 Agent 未正常完成"
            child_reads = [event for event in events if event["type"] == "tool_end" and event.get("subagent_id") and event["name"] == "read_file"]
            assert len(child_reads) >= 2, "子 Agent 未读取并读回验证"
            assert (tools.root / "result.txt").read_text(encoding="utf-8") == marker, "写入内容不匹配"
            assert marker in history[-1].get("content", ""), "主 Agent 未返回验证内容"
            assert not any(call["function"]["name"] in {"read_file", "write_file"} for message in history for call in message.get("tool_calls", [])), "子工具消息进入父历史或主 Agent 自己读写了文件"
            permission_events = [event for event in events if event["type"] == "hook_result" and event["hook_event"] == "PreToolUse" and event["hook_name"] == "permission_hook" and event["status"] == "passed"]
            assert any(event.get("subagent_id") for event in permission_events), "子 Agent 未经过权限 Hook"
            assert any(not event.get("subagent_id") for event in permission_events), "主 Agent 未经过权限 Hook"
            return {"status": "passed", "model": configured.model,
                    "model_calls": sum(event["type"] == "step_start" for event in events),
                    "delegations": sum(event["type"] == "subagent_start" for event in events),
                    "approved_writes": len(approved), "child_reads": len(child_reads),
                    "permission_hook_passes": len(permission_events),
                    "elapsed_seconds": round(time.monotonic()-started, 1),
                    "checks": ["parent delegation", "child file read", "approved child write", "child read-back", "parent final result", "isolated parent history"]}
        finally:
            if not worker.done():
                await runtime.stop(session)
            # sqlite3 connection context managers commit but do not close;
            # collect short-lived Store connections before Windows removes files.
            gc.collect()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(smoke()), ensure_ascii=False, indent=2))
    except Exception as error:
        # Assertions use fixed test messages; arbitrary remote errors stay private.
        print(json.dumps({"status": "failed", "error": str(error) if isinstance(error, (AssertionError, ValueError)) else type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)
