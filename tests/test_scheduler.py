import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app
from ecoder.runtime import Runtime, Run
from ecoder.scheduler import parse_cron, cron_matches, SHANGHAI
from test_harness import harness, ToolSequence, wait_for_approval
from test_subagent import tool_call


NOW = datetime(2026, 10, 23, 9, 0, tzinfo=SHANGHAI)  # Friday


class Success:
    def __init__(self):
        self.requests = []

    async def stream(self, messages, tools):
        self.requests.append(messages)
        yield {'type': 'response', 'message': {'role': 'assistant', 'content': 'scheduled result'}}


@pytest.mark.parametrize('cron,expected', [
    ('* * * * *', True), ('0 9 * * *', True), ('*/5 9 * * *', True),
    ('0 9 * * 1-5', True), ('0,30 8-10 * 10 5', True),
    ('1 9 * * *', False), ('0 10 * * *', False), ('0 9 * 11 *', False),
    ('0 9 1 * 5', True), ('0 9 23 * 0', True), ('0 9 1 * 0', False),
])
def test_cron_matching_and_day_weekday_or(cron, expected):
    assert cron_matches(cron, NOW) is expected


@pytest.mark.parametrize('cron', ['', '* * * *', '* * * * * *', '60 * * * *', '* 24 * * *',
    '* * 0 * *', '* * * 13 *', '* * * * 7', '*/0 * * * *', '5-1 * * * *',
    'a * * * *', '1,,2 * * * *', '1-5/2 * * * *'])
def test_invalid_cron_rejected(cron):
    with pytest.raises(ValueError):
        parse_cron(cron)


def test_sunday_is_zero_and_poll_uses_shanghai_time(harness):
    _, _, _, runtime, session = harness
    sunday = NOW + timedelta(days=2)
    assert cron_matches('0 9 * * 0', sunday)
    job = runtime.scheduler.schedule(session, '0 9 * * *', 'local time')
    runtime.scheduler.poll_due_jobs(NOW.astimezone(timezone.utc))
    assert runtime.scheduler.jobs[job['id']].pending_delivery
    assert runtime.scheduler.jobs[job['id']].last_fired == '2026-10-23 09:00'


def test_once_delivery_starts_real_loop_and_is_acknowledged(harness):
    _, store, _, runtime, session = harness
    runtime.provider = provider = Success()
    runtime.scheduler.now = lambda: NOW
    job = runtime.scheduler.schedule(session, '0 9 * * *', 'report status', recurring=False)
    async def scenario():
        runtime.scheduler.tick()
        await runtime.active[session].task
        runtime.scheduler.tick()
    asyncio.run(scenario())
    assert len(provider.requests) == 1
    assert provider.requests[0][-1]['content'] == '[Scheduled] report status'
    assert runtime.scheduler.list_jobs(session) == [] and store.crons() == []
    assert any(event['type'] == 'run_start' and event['schedule_id'] == job['id'] for event in store.events(session))
    assert store.events(session)[-1]['status'] == 'completed'


def test_recurring_deduplicates_minute_and_runs_next_match(harness):
    _, _, _, runtime, session = harness
    runtime.provider = provider = Success()
    moment = [NOW]
    runtime.scheduler.now = lambda: moment[0]
    runtime.scheduler.schedule(session, '* * * * *', 'recurring')
    async def scenario():
        runtime.scheduler.tick()
        await runtime.active[session].task
        runtime.scheduler.tick()
        assert len(provider.requests) == 1
        moment[0] += timedelta(minutes=1)
        runtime.scheduler.tick()
        await runtime.active[session].task
    asyncio.run(scenario())
    assert len(provider.requests) == 2
    assert not runtime.scheduler.list_jobs(session)[0]['pending_delivery']


def test_due_jobs_wait_for_user_run_or_upload(harness):
    _, _, _, runtime, session = harness
    runtime.provider = provider = Success()
    runtime.scheduler.now = lambda: NOW
    runtime.scheduler.schedule(session, '* * * * *', 'queued', recurring=False)
    async def scenario():
        runtime.active[session] = Run()
        runtime.scheduler.tick()
        assert runtime.scheduler.list_jobs(session)[0]['pending_delivery']
        assert not provider.requests
        runtime.active.pop(session)
        runtime.uploading.add(session)
        runtime.scheduler.tick()
        assert not provider.requests
        runtime.uploading.remove(session)
        runtime.scheduler.tick()
        await runtime.active[session].task
    asyncio.run(scenario())
    assert len(provider.requests) == 1


def test_queue_fairness_preserves_older_pending_delivery(harness):
    _, _, _, runtime, session = harness
    runtime.provider = provider = Success()
    moment = [NOW]
    runtime.scheduler.now = lambda: moment[0]
    runtime.scheduler.schedule(session, '* * * * *', 'first')
    runtime.scheduler.schedule(session, '* * * * *', 'second', recurring=False)
    async def scenario():
        runtime.scheduler.tick()
        await runtime.active[session].task
        # The recurring first job becomes due again, but the older second job
        # must be delivered first, even if first was registered earlier.
        moment[0] += timedelta(minutes=1)
        runtime.scheduler.tick()
        await runtime.active[session].task
    asyncio.run(scenario())
    assert provider.requests[1][-1]['content'] == '[Scheduled] second'


def test_durable_restore_pending_and_volatile_disappear(harness):
    settings, store, tools, runtime, session = harness
    durable = runtime.scheduler.schedule(session, '0 9 * * *', 'durable', recurring=False)
    runtime.scheduler.schedule(session, '* * * * *', 'temporary', durable=False)
    runtime.scheduler.poll_due_jobs(NOW)
    restored = Runtime(settings, store, tools, runtime.skills)
    restored.provider = provider = Success()
    restored.scheduler.now = lambda: NOW + timedelta(hours=1)
    assert [job['id'] for job in restored.scheduler.list_jobs(session)] == [durable['id']]
    async def scenario():
        restored.scheduler.tick()  # pending jobs deliver even outside matching minute
        await restored.active[session].task
    asyncio.run(scenario())
    assert len(provider.requests) == 1
    assert restored.scheduler.list_jobs(session) == []


def test_no_catch_up_for_time_missed_while_server_off(harness):
    settings, store, tools, runtime, session = harness
    runtime.scheduler.schedule(session, '0 9 * * *', 'missed')
    restored = Runtime(settings, store, tools, runtime.skills)
    restored.provider = provider = Success()
    restored.scheduler.tick(NOW + timedelta(minutes=1))
    assert not provider.requests and not restored.active
    assert not restored.scheduler.list_jobs(session)[0]['pending_delivery']


def test_provider_failure_retries_after_backoff_without_losing_job(harness):
    _, _, _, runtime, session = harness
    moment = [NOW]
    runtime.scheduler.now = lambda: moment[0]
    runtime.scheduler.schedule(session, '* * * * *', 'retry', recurring=False)
    class Failure:
        async def stream(self, *args):
            raise ValueError('test unavailable')
            yield
    runtime.provider = Failure()
    async def scenario():
        runtime.scheduler.tick()
        await runtime.active[session].task
        job = runtime.scheduler.list_jobs(session)[0]
        assert job['pending_delivery'] and job['next_attempt'] > NOW.timestamp()
        runtime.scheduler.tick()
        assert not runtime.active
        runtime.provider = provider = Success()
        moment[0] += timedelta(seconds=60)
        runtime.scheduler.tick()
        await runtime.active[session].task
        assert len(provider.requests) == 1
    asyncio.run(scenario())
    assert runtime.scheduler.list_jobs(session) == []


@pytest.mark.parametrize('allow', [True, False])
def test_scheduled_tools_still_use_permission_hooks(harness, allow):
    settings, store, _, runtime, session = harness
    runtime.provider = ToolSequence()
    runtime.scheduler.now = lambda: NOW
    runtime.scheduler.schedule(session, '* * * * *', 'write test', recurring=False)
    async def scenario():
        runtime.scheduler.tick()
        worker = runtime.active[session].task
        approval = await wait_for_approval(runtime, session)
        assert not (settings.workspace / 'approval_test.py').exists()
        runtime.approve(session, approval['approval_id'], allow)
        await worker
    asyncio.run(scenario())
    assert (settings.workspace / 'approval_test.py').exists() is allow
    assert any(event['type'] == 'hook_result' and event['hook_name'] == 'permission_hook' for event in store.events(session))


def test_cancel_queued_job_is_session_scoped(harness):
    _, store, _, runtime, session = harness
    runtime.provider = provider = Success()
    job = runtime.scheduler.schedule(session, '* * * * *', 'cancel')
    runtime.scheduler.poll_due_jobs(NOW)
    other = store.create_session()['id']
    with pytest.raises(ValueError):
        runtime.scheduler.cancel(other, job['id'])
    runtime.scheduler.cancel(session, job['id'])
    runtime.scheduler.tick(NOW)
    assert runtime.scheduler.list_jobs(session) == [] and not provider.requests
    assert store.crons() == []


def test_persistence_failure_never_exposes_undurable_queue(harness, monkeypatch):
    _, store, _, runtime, session = harness
    job = runtime.scheduler.schedule(session, '* * * * *', 'persist first')
    def fail(*args):
        raise OSError('test disk failure')
    monkeypatch.setattr(store, 'save_cron', fail)
    with pytest.raises(OSError):
        runtime.scheduler.poll_due_jobs(NOW)
    assert not runtime.scheduler.jobs[job['id']].pending_delivery
    assert runtime.scheduler.jobs[job['id']].last_fired is None
    with pytest.raises(OSError):
        runtime.scheduler.schedule(session, '* * * * *', 'must not appear')
    assert len(runtime.scheduler.list_jobs(session)) == 1


@pytest.mark.parametrize('shutdown,expected_pending', [(True, True), (False, False)])
def test_shutdown_preserves_unacknowledged_delivery_but_stop_skips_it(harness, shutdown, expected_pending):
    _, _, _, runtime, session = harness
    started = asyncio.Event()
    class Waiting:
        async def stream(self, *args):
            started.set()
            await asyncio.Event().wait()
            yield
    runtime.provider = Waiting()
    runtime.scheduler.now = lambda: NOW
    runtime.scheduler.schedule(session, '* * * * *', 'pending')
    async def scenario():
        runtime.scheduler.tick()
        await started.wait()
        await runtime.stop(session, shutdown=shutdown)
    asyncio.run(scenario())
    assert runtime.scheduler.list_jobs(session)[0]['pending_delivery'] is expected_pending


def test_schedule_tools_and_crud_api_with_session_deletion(harness):
    settings, store, _, runtime, session = harness
    async def scenario():
        result = await runtime.invoke(session, Run(), tool_call('schedule_cron', {'cron': '0 9 * * *', 'prompt': 'tool schedule'}))
        assert result['id'].startswith('cron_')
        listed = await runtime.invoke(session, Run(), tool_call('list_crons', {}))
        assert listed[0]['id'] == result['id']
        cancelled = await runtime.invoke(session, Run(), tool_call('cancel_cron', {'job_id': result['id']}))
        assert cancelled['cancelled']
    asyncio.run(scenario())
    with TestClient(create_app(settings)) as client:
        sid = client.post('/api/sessions').json()['id']
        route = f'/api/sessions/{sid}/crons'
        assert client.post(route, json={'cron': 'invalid', 'prompt': 'bad'}).status_code == 400
        assert client.post(route, json={'cron': '* * * * *', 'prompt': ' '}).status_code == 422
        job = client.post(route, json={'cron': '0 0 1 1 *', 'prompt': 'future'}).json()
        assert client.get(route).json()['crons'][0]['id'] == job['id']
        assert client.get(f'/api/sessions/{sid}').json()['crons'][0]['timezone'] == 'Asia/Shanghai'
        assert client.get('/api/status').json()['scheduler']['running']
        other = client.post('/api/sessions').json()['id']
        assert client.delete(f'/api/sessions/{other}/crons/{job["id"]}').status_code == 404
        assert client.delete(f'/api/sessions/{sid}').status_code == 200
        assert not client.app.state.runtime.scheduler.list_jobs(sid)
        assert not any(item['session'] == sid for item in client.app.state.store.crons())


def test_cron_update_alone_is_not_marked_as_interrupted_run(harness):
    settings, store, _, _, session = harness
    store.event(session, 'crons_update', crons=[])
    with TestClient(create_app(settings)):
        assert not any(event['type'] == 'run_end' for event in store.events(session))


def test_scheduler_lifecycle_has_no_import_side_effects(harness):
    _, _, _, runtime, _ = harness
    assert runtime.scheduler.task is None
    async def scenario():
        runtime.scheduler.start()
        task = runtime.scheduler.task
        runtime.scheduler.start()
        assert runtime.scheduler.task is task
        await runtime.scheduler.stop()
        assert task.done() and runtime.scheduler.task is None
    asyncio.run(scenario())


def test_failed_receipt_persistence_keeps_tool_protocol_complete(harness, monkeypatch):
    settings, store, _, runtime, session = harness
    runtime.provider = ToolSequence()
    runtime.scheduler.now = lambda: NOW
    runtime.scheduler.schedule(session, '* * * * *', 'ack failure', recurring=False)
    def fail(*args):
        raise OSError('test acknowledgement failure')
    monkeypatch.setattr(store, 'delete_cron', fail)
    async def scenario():
        runtime.scheduler.tick()
        await runtime.active[session].task
    asyncio.run(scenario())
    assert runtime.scheduler.list_jobs(session)[0]['pending_delivery']
    assert not (settings.workspace / 'approval_test.py').exists()
    history = store.messages(session)
    assert {call['id'] for message in history for call in message.get('tool_calls', [])} == {message['tool_call_id'] for message in history if message['role'] == 'tool'}
