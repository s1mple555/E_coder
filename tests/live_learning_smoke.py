import asyncio,json,tempfile,sys,gc
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecoder.config import Settings
from ecoder.store import Store
from ecoder.skills import Skills
from ecoder.tools import Tools
from ecoder.runtime import Runtime
async def main():
    with tempfile.TemporaryDirectory(prefix='ecoder-learning-') as folder:
        root=Path(folder);settings=replace(Settings.load(),root=root,workspace=root/'workspace')
        store=Store(root/'state.db');skills=Skills(root/'skills');runtime=Runtime(settings,store,Tools(settings.workspace,store,skills),skills)
        session=store.create_session()['id'];store.event(session,'user_message',run_id='synthetic',content='用Python写入UTF-8中文文件并验证')
        store.event(session,'run_start',run_id='synthetic')
        store.event(session,'tool_end',run_id='synthetic',name='run_command',result={'exit_code':0,'output':'UTF-8 write/read assertion passed; 3 test cases passed'})
        store.event(session,'run_end',run_id='synthetic',status='completed')
        rows=await runtime.learning.extract(session,'synthetic',True)
        assert rows and rows[0]['evidence']
        gc.collect()
        print(json.dumps({'status':'passed','lessons':len(rows),'evidence_valid':True},ensure_ascii=False))
asyncio.run(main())
