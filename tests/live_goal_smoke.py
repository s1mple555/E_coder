"""Opt-in real API check: .venv/Scripts/python.exe tests/live_goal_smoke.py.

Only synthetic text and an isolated temporary workspace are sent to the model.
Uses the configured model twice: actor and independent tool-free evaluator.
"""
import asyncio
from dataclasses import replace
import gc
import json
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecoder.config import Settings
from ecoder.runtime import Runtime
from ecoder.skills import Skills
from ecoder.store import Store
from ecoder.tools import Tools


async def smoke():
    configured=Settings.load()
    if not configured.api_key:
        raise ValueError('未配置 API Key')
    with tempfile.TemporaryDirectory(prefix='ecoder-goal-smoke-') as folder:
        root=Path(folder)
        settings=replace(configured,root=root,workspace=root/'workspace',max_steps=8,goal_block_cap=3)
        store,skills=Store(root/'state.db'),Skills(root/'skills')
        tools=Tools(settings.workspace,store,skills)
        marker='GOAL_VERIFIED_'+uuid.uuid4().hex[:12]
        (tools.root/'probe.txt').write_text(marker,encoding='utf-8')
        runtime=Runtime(settings,store,tools,skills)
        session=store.create_session('goal smoke test')['id']
        try:
            runtime.goals.start(session,'只读检查当前工作目录中的 probe.txt。验收条件：必须实际调用 read_file 读取文件，并在最终回答中包含完整文件内容。不要运行命令，也不要修改文件。')
            await asyncio.wait_for(runtime.active[session].task,180)
            goal=store.goal(session)
            assert goal['status']=='achieved','独立判断器没有确认达成目标'
            assert goal['judge_calls']>=1,'未调用独立判断器'
            assert marker in json.dumps(store.messages(session),ensure_ascii=False),'未读取实际测试内容'
            assert any(event['type']=='tool_end' and event['name']=='read_file' for event in store.events(session)),'没有真实读取工具证据'
            return {'status':'passed','model':configured.model,'goal_status':goal['status'],
                    'evaluations':goal['evaluations'],'agent_calls':goal['agent_calls'],'judge_calls':goal['judge_calls']}
        finally:
            if session in runtime.active:
                await runtime.stop(session)
            gc.collect()


if __name__=='__main__':
    try:
        print(json.dumps(asyncio.run(smoke()),ensure_ascii=False,indent=2))
    except Exception as error:
        print(json.dumps({'status':'failed','error':str(error) if isinstance(error,(ValueError,AssertionError)) else type(error).__name__},ensure_ascii=False))
        raise SystemExit(1)
