"""Opt-in real API test: .venv/Scripts/python.exe tests/live_cron_smoke.py.

Runs one background one-shot prompt in a temporary registry with synthetic text.
Uses configured credentials privately and consumes model tokens.
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
        raise ValueError('未配置 API Key')
    with tempfile.TemporaryDirectory(prefix='ecoder-cron-smoke-') as folder:
        root = Path(folder)
        settings = replace(configured, root=root, workspace=root/'workspace', max_steps=4)
        store, skills = Store(root/'state.db'), Skills(root/'skills')
        tools = Tools(settings.workspace, store, skills)
        runtime = Runtime(settings, store, tools, skills)
        session = store.create_session('cron smoke test')['id']
        marker = 'CRON_VERIFIED_' + uuid.uuid4().hex[:12]
        job = runtime.scheduler.schedule(session, '* * * * *', f'这是定时任务测试，只回复以下文本，不要调用工具：{marker}', recurring=False)
        started = time.monotonic()
        runtime.scheduler.start()
        try:
            while time.monotonic()-started < 180:
                events = store.events(session)
                if any(event['type'] == 'run_end' for event in events):
                    break
                await asyncio.sleep(0.1)
            else:
                raise ValueError('定时任务测试超过180秒')
            assert next(event for event in events if event['type']=='run_start')['schedule_id'] == job['id'], '未由调度器启动'
            assert next(event for event in events if event['type']=='run_end')['status'] == 'completed', '运行未正常完成'
            assert marker in store.messages(session)[-1].get('content', ''), '模型未返回测试文本'
            assert not runtime.scheduler.list_jobs(session) and not store.crons(), '单次交付未清除'
            return {'status':'passed', 'model':configured.model, 'timezone':'Asia/Shanghai',
                    'background_trigger':True, 'one_shot_acknowledged':True,
                    'elapsed_seconds':round(time.monotonic()-started,1)}
        finally:
            await runtime.scheduler.stop()
            if session in runtime.active:
                await runtime.stop(session, shutdown=True)
            gc.collect()


if __name__ == '__main__':
    try:
        print(json.dumps(asyncio.run(smoke()), ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({'status':'failed','error':str(error) if isinstance(error,(ValueError,AssertionError)) else type(error).__name__},ensure_ascii=False))
        raise SystemExit(1)
