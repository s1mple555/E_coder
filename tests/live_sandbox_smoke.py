"""Opt-in configured-model + permission + native sandbox integration test."""
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
    if not configured.api_key:raise ValueError('未配置 API Key')
    with tempfile.TemporaryDirectory(prefix='ecoder-sandbox-smoke-') as folder:
        root=Path(folder)
        settings=replace(configured,root=root,workspace=root/'workspace',max_steps=5)
        store,skills=Store(root/'state.db'),Skills(root/'skills')
        tools=Tools(settings.workspace,store,skills)
        runtime=Runtime(settings,store,tools,skills)
        session=store.create_session('sandbox smoke')['id']
        marker='SANDBOX_'+uuid.uuid4().hex[:12]
        (tools.root/'probe.txt').write_text(marker,encoding='utf-8')
        code="from pathlib import Path; data=Path('probe.txt').read_text(encoding='utf-8'); Path('result.txt').write_text(data,encoding='utf-8'); print(data)"
        argv=[sys.executable,'-c',code]
        prompt='这是合成测试。只调用一次 run_command，execution_mode 必须为 sandbox，timeout=15，argv 严格使用以下 JSON 数组，然后总结输出。不得调用其他工具或主机模式：'+json.dumps(argv,ensure_ascii=False)
        runtime.start(session,prompt)
        worker=runtime.active[session].task
        approved=0
        async def approvals():
            nonlocal approved
            while not worker.done():
                for item in runtime.pending(session):
                    args=item['arguments']
                    allow=item['name']=='run_command' and args.get('execution_mode')=='sandbox' and args.get('argv')==argv
                    runtime.approve(session,item['approval_id'],allow)
                    approved+=int(allow)
                await asyncio.sleep(.1)
        approver=asyncio.create_task(approvals())
        try:
            await asyncio.wait_for(worker,150)
            assert approved==1,'没有严格匹配预期的沙箱审批'
            assert (tools.root/'result.txt').read_text(encoding='utf-8')==marker,'沙箱没有正确同步结果'
            results=[e.get('result',{}) for e in store.events(session) if e['type']=='tool_end' and e.get('name')=='run_command']
            assert any(r.get('sandbox')=='windows-appcontainer' and r.get('exit_code')==0 and marker in r.get('output','') for r in results),'没有 OS 沙箱执行证据'
            return {'status':'passed','model':configured.model,'approved':approved,'sandbox':'windows-appcontainer','file_sync':True}
        finally:
            approver.cancel()
            await asyncio.gather(approver,return_exceptions=True)
            if session in runtime.active:await runtime.stop(session)
            gc.collect()


if __name__=='__main__':
    try:print(json.dumps(asyncio.run(smoke()),ensure_ascii=False,indent=2))
    except Exception as error:
        print(json.dumps({'status':'failed','error':str(error) if isinstance(error,(ValueError,AssertionError)) else type(error).__name__},ensure_ascii=False))
        raise SystemExit(1)
