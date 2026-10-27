import asyncio
import json
import time
from test_harness import harness
from test_features import seed,Reflector


def test_queued_learning_does_not_move_to_new_workspace(harness,tmp_path):
    _,store,tools,runtime,session=harness;seq=seed(store,session);runtime.learning.provider=Reflector(seq)
    async def scenario():
        lock=runtime.learning.locks.setdefault(session,asyncio.Lock());await lock.acquire()
        job=runtime.learning.submit(session,'r',True)
        await asyncio.sleep(0)
        tools.root=tmp_path/'changed';tools.root.mkdir();lock.release()
        await runtime.learning.tasks[job['id']]
    asyncio.run(scenario())
    with store.connect() as db:job=json.loads(db.execute('SELECT body FROM learning_jobs').fetchone()[0])
    assert job['status']=='failed' and job['error_code']=='workspace_changed'
    assert runtime.learning.list(session)==[]


def test_session_summary_freezes_confirmed_runs_when_queued(harness):
    _,store,_,runtime,session=harness;seq=seed(store,session);reflector=Reflector(seq);runtime.learning.provider=reflector
    async def scenario():
        lock=runtime.learning.locks.setdefault(session,asyncio.Lock());await lock.acquire()
        job=runtime.learning.submit(session,'',True,source_scope='session')
        store.event(session,'user_message',run_id='later',content='NEW_UNCONFIRMED_TASK')
        store.event(session,'run_start',run_id='later')
        store.event(session,'tool_end',run_id='later',name='read_file',result={'text':'later'})
        store.event(session,'run_end',run_id='later',status='completed')
        lock.release();await runtime.learning.tasks[job['id']]
    asyncio.run(scenario())
    assert 'NEW_UNCONFIRMED_TASK' not in reflector.requests[0][-1]['content']


def test_delete_during_reflection_is_not_undone_by_its_result(harness):
    _,store,_,runtime,session=harness;seq=seed(store,session);runtime.learning.provider=Reflector(seq)
    lesson=asyncio.run(runtime.learning.extract(session,'r',True))[0]
    class DeletingReflector(Reflector):
        async def stream(self,*args):
            runtime.learning.delete(session,lesson['id'])
            async for event in super().stream(*args):yield event
    runtime.learning.provider=DeletingReflector(seq)
    assert asyncio.run(runtime.learning.extract(session,'r',True))==[]
    runtime.learning.provider=Reflector(seq)
    assert len(asyncio.run(runtime.learning.extract(session,'r',True)))==1


def test_deleting_original_session_preserves_shared_experience_and_valid_sources(harness):
    _,store,_,runtime,first=harness;runtime.learning.provider=Reflector(seed(store,first))
    original=asyncio.run(runtime.learning.extract(first,'r',True))[0]
    second=store.create_session()['id'];runtime.learning.provider=Reflector(seed(store,second))
    assert asyncio.run(runtime.learning.extract(second,'r',True))[0]['id']==original['id']
    assert store.delete_session(first)
    remaining=runtime.learning.list(second)
    assert len(remaining)==1 and remaining[0]['source_session']==second
    assert all(source['session']==second for source in remaining[0]['sources'])
    assert remaining[0]['confirmations']==1
    assert store.delete_session(second)
    with store.connect() as db:assert db.execute('SELECT count(*) FROM experiences').fetchone()[0]==0


def test_retrieved_experience_context_keeps_whole_valid_json(harness,monkeypatch):
    _,store,_,runtime,session=harness
    store.append(session,{'role':'user','content':'验证'})
    rows=[{'id':str(index),'title':'验证方法','when':'验证'+'适用'*249,'strategy':'方法'*800,'evidence':[1],'enabled':True,'sources':['metadata'*1000]} for index in range(5)]
    monkeypatch.setattr(runtime.learning,'list',lambda session:rows)
    context=runtime.learning.context(session);document=json.loads(context.splitlines()[-1])
    assert 1<=len(document)<5
    assert len(json.dumps(document,ensure_ascii=False))<=10000
    assert all(len(row['strategy'])==1600 and 'sources' not in row for row in document)
