import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import create_app
from ecoder.goals import parse_evaluation, transcript_text
from ecoder.runtime import Runtime
from test_harness import harness, ToolSequence, wait_for_approval
from test_subagent import DelegationSequence


class MainText:
    def __init__(self, text='work result'):
        self.requests = []
        self.text = text

    async def stream(self, messages, tools):
        self.requests.append(messages)
        yield {'type':'usage','total_tokens':10}
        yield {'type':'usage','total_tokens':12}
        yield {'type':'response','message':{'role':'assistant','content':self.text}}


class Judge:
    def __init__(self, decisions):
        self.decisions, self.requests = list(decisions), []

    async def stream(self, messages, tools):
        assert tools == []
        self.requests.append(messages)
        value = self.decisions.pop(0)
        if isinstance(value,Exception):
            raise value
        yield {'type':'usage','total_tokens':5}
        yield {'type':'usage','total_tokens':7}
        yield {'type':'response','message':{'role':'assistant','content':json.dumps(value) if isinstance(value,dict) else value}}


def decision(ok, reason='evidence checked', impossible=False):
    return {'ok':ok,'reason':reason,'impossible':impossible}


def run_goal(runtime, session, condition='check concrete evidence'):
    async def scenario():
        runtime.goals.start(session,condition)
        await runtime.active[session].task
    asyncio.run(scenario())


def test_goal_continues_until_independent_evaluator_accepts(harness):
    _, store, _, runtime, session = harness
    runtime.provider = main = MainText('claimed complete')
    runtime.goal_provider = judge = Judge([decision(False,'missing actual test output'),decision(True)])
    run_goal(runtime,session)
    state = store.goal(session)
    assert state['status']=='achieved' and state['evaluations']==2
    assert len(main.requests)==2 and len(judge.requests)==2
    assert 'missing actual test output' in main.requests[1][-1]['content']
    assert state['agent_tokens']==24 and state['judge_tokens']==14
    assert state['agent_calls']==2 and state['judge_calls']==2
    assert state['reported_calls']==4
    assert any(event['type']=='hook_result' and event['hook_event']=='Stop' for event in store.events(session))
    assert store.events(session)[-1]['status']=='completed'


def test_no_goal_means_no_judge_call(harness):
    _, _, _, runtime, session = harness
    runtime.provider = MainText()
    runtime.goal_provider = judge = Judge([])
    async def scenario():
        runtime.start(session,'ordinary chat')
        await runtime.active[session].task
    asyncio.run(scenario())
    assert not judge.requests


@pytest.mark.parametrize('value',[{}, [], {'ok':'true','reason':'x'}, {'ok':True,'reason':''},
    {'ok':True,'reason':'x','impossible':True}, {'ok':False,'reason':'x','impossible':'false'}])
def test_judge_requires_strict_consistent_json(value):
    with pytest.raises(ValueError):
        parse_evaluation(json.dumps(value))


def test_judge_accepts_fenced_json_and_transcript_keeps_real_tool_arguments():
    assert parse_evaluation('```json\n{"ok":true,"reason":"done"}\n```')['ok']
    messages=[{'role':'assistant','content':None,'tool_calls':[{'id':'c','function':{'name':'run_command','arguments':'{"argv":["python","-V"]}'}}]},
              {'role':'tool','tool_call_id':'c','content':'{"exit_code":0}'}]
    text=transcript_text(messages)
    assert 'run_command' in text and 'exit_code' in text
    large=transcript_text([{'role':'tool','content':'HEAD'+'x'*50000+'TAIL'}],1000)
    assert 'HEAD' in large and 'TAIL' in large and len(large)<=1000


@pytest.mark.parametrize('result', ['not-json', RuntimeError('private-remote-error')])
def test_judge_failure_retains_goal_and_never_claims_success(harness,result):
    _, store, _, runtime, session = harness
    runtime.provider = main = MainText()
    runtime.goal_provider = Judge([result])
    run_goal(runtime,session)
    assert store.goal(session)['status']=='evaluation_failed'
    assert len(main.requests)==1
    assert store.events(session)[-1]['status']=='failed'
    assert 'private-remote-error' not in json.dumps(store.events(session))


def test_impossible_stops_with_reason_and_no_success(harness):
    _, store, _, runtime, session = harness
    runtime.provider = MainText()
    runtime.goal_provider = Judge([decision(False,'required resource is unavailable',True)])
    run_goal(runtime,session)
    assert store.goal(session)['status']=='impossible'
    assert store.events(session)[-1]['status']=='failed'


def test_continuation_cap_retains_unfinished_target(harness):
    settings, store, _, runtime, session = harness
    settings.goal_block_cap=2
    runtime.provider = main = MainText()
    runtime.goal_provider = Judge([decision(False),decision(False)])
    run_goal(runtime,session)
    assert store.goal(session)['status']=='limit_reached'
    assert len(main.requests)==2
    assert store.events(session)[-1]['status']=='limit_reached'


def test_global_step_limit_does_not_complete_goal(harness):
    settings, store, _, runtime, session = harness
    settings.max_steps=1
    runtime.provider=MainText()
    runtime.goal_provider=Judge([decision(False)])
    run_goal(runtime,session)
    assert store.goal(session)['status']=='limit_reached'


def test_pause_resume_clear_and_restart_recovery(harness):
    settings, store, tools, runtime, session = harness
    started=asyncio.Event()
    class Waiting:
        async def stream(self,*args):
            started.set()
            await asyncio.Event().wait()
            yield
    runtime.provider=Waiting()
    async def scenario():
        runtime.goals.start(session,'work until verified')
        await started.wait()
        await runtime.goals.control(session,'pause')
        assert store.goal(session)['status']=='paused' and session not in runtime.active
        runtime.provider=MainText()
        runtime.goal_provider=Judge([decision(True)])
        await runtime.goals.control(session,'resume')
        await runtime.active[session].task
        assert store.goal(session)['status']=='achieved'
        runtime.goals.set_goal(session,'new unfinished goal')
        restored=Runtime(settings,store,tools,runtime.skills)
        restored.goals.recover()
        assert store.goal(session)['status']=='interrupted' and not restored.active
        await restored.goals.control(session,'clear')
        assert store.goal(session)['status']=='cancelled'
    asyncio.run(scenario())


def test_goal_scope_excludes_previous_claims_and_other_sessions(harness):
    _, store, _, runtime, session = harness
    store.append(session,{'role':'assistant','content':'OLD_SUCCESS_SHOULD_NOT_COUNT'})
    runtime.provider=MainText()
    runtime.goal_provider=judge=Judge([decision(True)])
    run_goal(runtime,session)
    assert 'OLD_SUCCESS_SHOULD_NOT_COUNT' not in json.dumps(judge.requests)
    other=store.create_session()['id']
    assert runtime.goals.status(other) is None
    store.delete_session(session)
    assert store.goal(session) is None


def test_goal_preserves_existing_permission_and_approval(harness):
    settings, store, _, runtime, session = harness
    runtime.provider=ToolSequence()
    runtime.goal_provider=Judge([decision(True)])
    async def scenario():
        runtime.goals.start(session,'write and verify')
        worker=runtime.active[session].task
        approval=await wait_for_approval(runtime,session)
        assert not (settings.workspace/'approval_test.py').exists()
        runtime.approve(session,approval['approval_id'],True)
        await worker
    asyncio.run(scenario())
    assert (settings.workspace/'approval_test.py').exists()
    assert store.goal(session)['status']=='achieved'


def test_subagent_cannot_judge_or_complete_parent_goal(harness):
    settings, store, _, runtime, session = harness
    (settings.workspace/'sample.txt').write_text('sample',encoding='utf-8')
    runtime.provider=DelegationSequence()
    runtime.goal_provider=judge=Judge([decision(True)])
    run_goal(runtime,session)
    assert len(judge.requests)==1
    assert store.goal(session)['agent_calls']==4  # parent and child calls


def test_scheduled_turn_does_not_adopt_unrelated_goal(harness):
    _, store, _, runtime, session = harness
    runtime.goals.set_goal(session,'user goal')
    runtime.provider=MainText()
    runtime.goal_provider=judge=Judge([])
    async def scenario():
        runtime.start(session,'[Scheduled] other task',schedule_id='not-a-real-job')
        await runtime.active[session].task
    asyncio.run(scenario())
    assert not judge.requests and store.goal(session)['status']=='active'


def test_goal_api_and_slash_commands(harness):
    settings,*_=harness
    app=create_app(settings)
    app.state.runtime.provider=MainText()
    app.state.runtime.goal_provider=Judge([decision(True)])
    with TestClient(app) as client:
        session=client.post('/api/sessions').json()['id']
        base=f'/api/sessions/{session}'
        assert client.get(base+'/goal').json()=={'goal':None}
        assert client.post(base+'/goal',json={'condition':' '}).status_code==422
        result=client.post(base+'/runs',json={'message':'/goal show concrete result'}).json()
        assert result['run_id']
        for _ in range(100):
            data=client.get(base).json()
            if not data['running']:
                break
            time.sleep(.01)
        assert data['goal']['status']=='achieved'
        status=client.post(base+'/runs',json={'message':'/goal'}).json()
        assert status['run_id'] is None and status['goal']['status']=='achieved'
        assert client.post(base+'/goal/control',json={'action':'complete'}).status_code==422
        assert client.post(base+'/goal/control',json={'action':'resume'}).status_code==409
        assert client.delete(base).status_code==200
        assert app.state.store.goal(session) is None
