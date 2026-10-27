import asyncio
import json
import threading
import time
import pytest
from fastapi.testclient import TestClient
from app import create_app
from ecoder.learning import Learning
from test_harness import harness
from test_features import seed


def test_background_job_survives_request_return_and_supports_multiple_lessons_and_delete(harness):
    settings,*_=harness
    app=create_app(settings);runtime=app.state.runtime
    started=threading.Event();release=threading.Event();calls=[]
    class SlowReflector:
        async def stream(self,messages,tools):
            calls.append(messages);started.set()
            while not release.is_set():await asyncio.sleep(.01)
            seq=json.loads(messages[-1]['content'])['allowed_success_evidence'][0]
            lessons=[{'title':f'方法 {i}','when':f'适用场景 {i}','strategy':f'定位问题 {i}，修复后运行验证。','evidence':[seq]} for i in range(3)]
            yield {'type':'response','message':{'content':json.dumps({'lessons':lessons})}}
    runtime.learning.provider=SlowReflector()
    with TestClient(app) as client:
        session=client.post('/api/sessions').json()['id'];prefix=f'/api/sessions/{session}/experiences';seed(runtime.store,session)
        result=client.post(prefix+'/jobs',json={'run_id':'r','confirmed':True})
        assert result.status_code==202 and started.wait(1)
        identifier=result.json()['job']['id']
        # Independent GET requests model refreshing/reopening the page.
        for _ in range(2):assert client.get(prefix).json()['jobs'][0]['id']==identifier
        duplicate=client.post(prefix+'/jobs',json={'run_id':'r','confirmed':True})
        assert duplicate.json()['job']['id']==identifier and len(calls)==1
        another=client.post('/api/sessions').json()['id']
        assert client.get(f'/api/sessions/{another}/experiences').json()['jobs']==[]
        release.set()
        for _ in range(100):
            data=client.get(prefix).json()
            if data['jobs'][0]['status']=='completed':break
            time.sleep(.01)
        assert data['jobs'][0]['status']=='completed' and data['jobs'][0]['result_count']==3
        assert len(data['experiences'])==3
        lesson=data['experiences'][0]
        assert client.delete(prefix+'/'+lesson['id']).status_code==200
        assert len(client.get(prefix).json()['experiences'])==2
        runtime.store.append(session,{'role':'user','content':lesson['when']})
        assert lesson['title'] not in runtime.learning.context(session)
        assert client.delete(prefix+'/'+lesson['id']).status_code==404


def test_shutdown_marks_pending_job_interrupted_and_restart_retains_state(harness):
    _,store,_,runtime,session=harness;seed(store,session)
    started=asyncio.Event()
    class WaitingReflector:
        async def stream(self,*args):
            started.set();await asyncio.Event().wait()
            yield {}
    runtime.learning.provider=WaitingReflector()
    async def scenario():
        runtime.learning.submit(session,'r',True)
        await started.wait();await runtime.learning.stop()
    asyncio.run(scenario())
    assert runtime.learning.jobs(session)[0]['status']=='interrupted'
    restored=Learning(runtime);restored.recover()
    assert restored.jobs(session)[0]['status']=='interrupted' and not restored.tasks


def test_background_failure_is_persisted_and_delete_is_scope_checked(harness,tmp_path):
    _,store,tools,runtime,session=harness;seq=seed(store,session)
    class InvalidReflector:
        async def stream(self,*args):yield {'type':'response','message':{'content':'invalid-json'}}
    runtime.learning.provider=InvalidReflector()
    async def scenario():
        job=runtime.learning.submit(session,'r',True)
        await runtime.learning.tasks[job['id']]
    asyncio.run(scenario())
    job=runtime.learning.jobs(session)[0]
    assert job['status']=='failed' and job['error_code']=='invalid_json'
    assert 'JSON' in job['error'] and runtime.learning.list(session)==[]
    from test_features import Reflector
    runtime.learning.provider=Reflector(seq)
    lesson=asyncio.run(runtime.learning.extract(session,'r',True))[0]
    old=tools.root;tools.root=tmp_path/'other';tools.root.mkdir()
    with pytest.raises(ValueError):runtime.learning.delete(session,lesson['id'])
    tools.root=old
    assert len(runtime.learning.list(session))==1
    assert store.delete_session(session)
    with store.connect() as db:assert db.execute('SELECT count(*) FROM learning_jobs WHERE session=?',(session,)).fetchone()[0]==0


def test_session_focus_reaches_reflector_and_preserves_each_evidence_source(harness):
    settings,*_=harness;app=create_app(settings);runtime=app.state.runtime;requests=[]
    class FocusReflector:
        async def stream(self,messages,tools):
            document=json.loads(messages[-1]['content']);requests.append(document)
            lessons=[{'title':'Windows 路径验证','when':'Windows 命令执行','strategy':'先验证路径和引号，再检查退出码。','evidence':document['allowed_success_evidence']}]
            yield {'type':'response','message':{'content':json.dumps({'lessons':lessons})}}
    runtime.learning.provider=FocusReflector()
    with TestClient(app) as client:
        session=client.post('/api/sessions').json()['id'];prefix=f'/api/sessions/{session}/experiences';seed(runtime.store,session)
        runtime.store.event(session,'user_message',run_id='r2',content='验证带空格的 Windows 路径')
        runtime.store.event(session,'run_start',run_id='r2')
        runtime.store.event(session,'tool_end',run_id='r2',name='run_command',result={'exit_code':0,'output':'PATH_OK'})
        runtime.store.event(session,'run_end',run_id='r2',status='completed')
        focus='总结 Windows 路径与终端命令的问题'
        response=client.post(prefix+'/jobs',json={'source_scope':'session','focus':focus,'confirmed':True})
        assert response.status_code==202
        for _ in range(100):
            data=client.get(prefix).json()
            if data['jobs'][0]['status']=='completed':break
            time.sleep(.01)
        assert data['jobs'][0]['focus']==focus and data['jobs'][0]['result_count']==1
        assert requests[0]['summary_focus']==focus and requests[0]['source_scope']=='session'
        assert 'Python 文件写入' in requests[0]['task'] and 'Windows 路径' in requests[0]['task']
        assert {source['run_id'] for source in data['experiences'][0]['sources']}=={'r','r2'}
        assert client.post(prefix+'/jobs',json={'source_scope':'invalid','confirmed':True}).status_code==422
        assert client.post(prefix+'/jobs',json={'focus':'x'*2001,'confirmed':True}).status_code==422


def test_different_focus_does_not_deduplicate_into_wrong_running_job(harness):
    _,store,_,runtime,session=harness;seed(store,session)
    class FocusReflector:
        async def stream(self,messages,tools):yield {'type':'response','message':{'content':'{"lessons":[]}'}}
    runtime.learning.provider=FocusReflector()
    async def scenario():
        first=runtime.learning.submit(session,'r',True,focus='路径问题')
        assert runtime.learning.submit(session,'r',True,focus='路径问题')['id']==first['id']
        other=runtime.learning.submit(session,'r',True,focus='编码问题')
        assert first['id']!=other['id']
        await asyncio.gather(*list(runtime.learning.tasks.values()))
    asyncio.run(scenario())
    assert len(runtime.learning.jobs(session))==2


def test_all_experiences_aggregates_workspaces_without_duplicates_and_allows_management(harness):
    from test_features import Reflector
    settings,*_=harness;app=create_app(settings);runtime=app.state.runtime
    with TestClient(app) as client:
        first=client.post('/api/sessions').json()['id']
        runtime.learning.provider=Reflector(seed(runtime.store,first))
        lesson=asyncio.run(runtime.learning.extract(first,'r',True))[0]
        shared=client.post('/api/sessions').json()['id']
        runtime.learning.provider=Reflector(seed(runtime.store,shared))
        assert asyncio.run(runtime.learning.extract(shared,'r',True))[0]['id']==lesson['id']
        second=client.post('/api/sessions').json()['id'];folder=settings.root/'other-project';folder.mkdir()
        assert client.post(f'/api/sessions/{second}/folder',json={'path':str(folder)}).status_code==200
        runtime.learning.provider=Reflector(seed(runtime.store,second))
        other=asyncio.run(runtime.learning.extract(second,'r',True))[0]
        assert other['id']!=lesson['id']
        rows=client.get('/api/experiences').json()['experiences']
        assert len(rows)==2 and len({row['id'] for row in rows})==2
        assert all('source_session_title' in row for row in rows)
        assert len(client.get(f'/api/sessions/{first}/experiences').json()['experiences'])==1
        assert client.patch(f'/api/sessions/{first}/experiences/{other["id"]}',json={'enabled':False}).status_code==400
        assert client.patch(f'/api/experiences/{other["id"]}',json={'enabled':False}).status_code==200
        assert not next(row for row in client.get('/api/experiences').json()['experiences'] if row['id']==other['id'])['enabled']
        assert client.delete(f'/api/experiences/{other["id"]}').status_code==200
        assert len(client.get('/api/experiences').json()['experiences'])==1
