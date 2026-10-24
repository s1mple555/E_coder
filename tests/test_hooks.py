import asyncio
import json

import pytest

from ecoder.hooks import Hooks, HookError
from ecoder.runtime import Run
from test_harness import harness, ToolSequence, wait_for_approval
from test_subagent import DelegationSequence, tool_call


def test_hooks_order_sync_async_and_first_result():
    hooks, seen = Hooks(), []
    def late(context):
        seen.append('late')
    async def first(context):
        seen.append('first')
    def block(context):
        seen.append(context)
        return 'blocked'
    hooks.register_hook('PreToolUse', late, priority=100)
    hooks.register_hook('PreToolUse', first)
    hooks.register_hook('PreToolUse', block)
    assert asyncio.run(hooks.trigger_hooks('PreToolUse', 'context')) == 'blocked'
    assert seen == ['first', 'context']
    assert asyncio.run(Hooks().trigger_hooks('PreToolUse', None)) is None


def test_registries_are_independent_and_snapshot_registration():
    hooks, seen = Hooks(), []
    def added(context):
        seen.append('added')
    def first(context):
        hooks.register_hook('Stop', added)
        seen.append('first')
    hooks.register_hook('Stop', first)
    asyncio.run(hooks.trigger_hooks('Stop', None))
    assert seen == ['first']
    asyncio.run(Hooks().trigger_hooks('Stop', None))
    assert seen == ['first']
    asyncio.run(hooks.trigger_hooks('Stop', None))
    assert seen == ['first', 'first', 'added']
    with pytest.raises(ValueError):
        hooks.register_hook('Typo', added)
    with pytest.raises(TypeError):
        hooks.register_hook('Stop', None)


@pytest.mark.parametrize('result', [False, {}, ''])
def test_invalid_hook_results_fail_closed(result):
    hooks = Hooks()
    hooks.register_hook('PreToolUse', lambda context: result)
    with pytest.raises(HookError):
        asyncio.run(hooks.trigger_hooks('PreToolUse', None))


def test_pre_hook_blocks_before_approval_and_execution(harness):
    settings, store, _, runtime, session = harness
    post_calls = []
    runtime.hooks.register_hook('PreToolUse', lambda context: 'denied by extension')
    runtime.hooks.register_hook('PostToolUse', lambda context: post_calls.append(context))
    result = asyncio.run(runtime.invoke(session, Run(), tool_call('write_file', {'path': 'blocked.txt', 'content': 'no'})))
    assert result == {'error': 'denied by extension'}
    assert not (settings.workspace / 'blocked.txt').exists()
    assert not post_calls
    assert not any(event['type'] == 'approval_request' for event in store.events(session))


def test_pre_hook_failure_does_not_execute_or_leak_exception(harness):
    settings, store, _, runtime, session = harness
    def broken(context):
        raise RuntimeError('secret-value')
    runtime.hooks.register_hook('PreToolUse', broken)
    result = asyncio.run(runtime.invoke(session, Run(), tool_call('write_file', {'path': 'blocked.txt', 'content': 'no'})))
    assert 'Hook' in result['error'] and 'secret-value' not in result['error']
    assert not (settings.workspace / 'blocked.txt').exists()
    assert any(event['type'] == 'hook_result' and event['status'] == 'failed' for event in store.events(session))


@pytest.mark.parametrize('allow', [True, False])
def test_permission_is_registered_hook_and_post_only_after_execution(harness, allow):
    settings, store, _, runtime, session = harness
    observed = []
    runtime.hooks.register_hook('PostToolUse', lambda context: observed.append((context.name, context.result)))
    async def scenario():
        runtime.active[session] = run = Run()
        worker = asyncio.create_task(runtime.invoke(session, run, tool_call('write_file', {'path': 'approved.txt', 'content': 'yes'})))
        approval = await wait_for_approval(runtime, session)
        assert not (settings.workspace / 'approved.txt').exists()
        runtime.approve(session, approval['approval_id'], allow)
        result = await worker
        assert ('error' not in result) is allow
        assert runtime.pending(session) == []
        runtime.active.pop(session)
    asyncio.run(scenario())
    assert (settings.workspace / 'approved.txt').exists() is allow
    assert bool(observed) is allow
    assert any(event['type'] == 'hook_result' and event['hook_name'] == 'permission_hook' and event['status'] == ('passed' if allow else 'returned') for event in store.events(session))


def test_permission_timeout_removes_approval_and_does_not_write(harness):
    settings, store, _, runtime, session = harness
    runtime.approval_timeout = 0.01
    run = Run()
    result = asyncio.run(runtime.invoke(session, run, tool_call('write_file', {'path': 'timeout.txt', 'content': 'no'})))
    assert '审批超时' in result['error']
    assert run.approvals == {}
    assert not (settings.workspace / 'timeout.txt').exists()
    assert any(event['type'] == 'approval_result' and event.get('reason') == 'timeout' for event in store.events(session))


def test_permission_approved_snapshot_still_rejects_external_change(harness):
    settings, _, _, runtime, session = harness
    target = settings.workspace / 'changed.txt'
    target.write_text('original', encoding='utf-8')
    async def scenario():
        runtime.active[session] = run = Run()
        worker = asyncio.create_task(runtime.invoke(session, run, tool_call('edit_file', {'path': 'changed.txt', 'old_text': 'original', 'new_text': 'replacement'})))
        approval = await wait_for_approval(runtime, session)
        target.write_text('external change', encoding='utf-8')
        runtime.approve(session, approval['approval_id'], True)
        result = await worker
        assert '审批期间' in result['error']
        runtime.active.pop(session)
    asyncio.run(scenario())
    assert target.read_text(encoding='utf-8') == 'external change'


def test_post_failure_preserves_actual_execution_result(harness):
    settings, store, _, runtime, session = harness
    def broken(context):
        context.result.clear()
        raise RuntimeError('private-output')
    runtime.hooks.register_hook('PostToolUse', broken)
    original = runtime.emit
    run = Run()
    runtime.active[session] = run
    def approve(session, run, kind, **data):
        event = original(session, run, kind, **data)
        if kind == 'approval_request':
            runtime.approve(session, data['approval_id'], True)
        return event
    runtime.emit = approve
    result = asyncio.run(runtime.invoke(session, run, tool_call('write_file', {'path': 'done.txt', 'content': 'done'})))
    assert result['bytes'] == 4 and 'error' not in result
    assert (settings.workspace / 'done.txt').read_text() == 'done'
    assert 'private-output' not in json.dumps(store.events(session))
    assert any(event['type'] == 'notice' for event in store.events(session))


def test_user_prompt_hook_can_reject_before_model_request(harness):
    _, store, _, runtime, session = harness
    class NeverCalled:
        async def stream(self, *args):
            raise AssertionError('model must not be called')
            yield
    runtime.provider = NeverCalled()
    seen = []
    def reject(context):
        seen.append(context.prompt)
        return 'test rejection'
    runtime.hooks.register_hook('UserPromptSubmit', reject)
    async def scenario():
        runtime.start(session, 'user prompt')
        await runtime.active[session].task
    asyncio.run(scenario())
    assert seen == ['user prompt']
    assert store.events(session)[-1]['status'] == 'failed'
    assert not any(event['type'] == 'step_start' for event in store.events(session))


@pytest.mark.parametrize('always_continue', [False, True])
def test_stop_hook_continues_but_respects_step_limit(harness, always_continue):
    _, store, _, runtime, session = harness
    runtime.settings.max_steps = 3
    seen = []
    requests = []
    class FinalText:
        async def stream(self, messages, tools):
            requests.append(messages)
            yield {'type': 'response', 'message': {'role': 'assistant', 'content': 'final'}}
    runtime.provider = FinalText()
    def verify(context):
        seen.append(context.run.subagent_id)
        if always_continue or len(seen) == 1:
            return 'perform one more verification'
    runtime.hooks.register_hook('Stop', verify)
    async def scenario():
        runtime.start(session, 'task')
        await runtime.active[session].task
    asyncio.run(scenario())
    assert len(requests) == (3 if always_continue else 2)
    assert '[Stop Hook]' in requests[1][-1]['content']
    assert store.events(session)[-1]['status'] == ('limit_reached' if always_continue else 'completed')


def test_parent_and_child_share_hooks_and_permission_audit(harness):
    settings, store, _, runtime, session = harness
    (settings.workspace / 'sample.txt').write_text('sample', encoding='utf-8')
    runtime.provider = DelegationSequence()
    stops, post = [], []
    runtime.hooks.register_hook('Stop', lambda context: stops.append(context.run.subagent_id))
    runtime.hooks.register_hook('PostToolUse', lambda context: post.append((context.name, context.run.subagent_id)))
    async def scenario():
        runtime.start(session, 'delegate')
        await runtime.active[session].task
    asyncio.run(scenario())
    assert stops[0] is not None and stops[1] is None
    assert post[0][0] == 'read_file' and post[0][1] is not None
    assert post[1] == ('sub_agent', None)
    assert any(event['type'] == 'hook_result' and event.get('subagent_id') and event['hook_name'] == 'permission_hook' for event in store.events(session))


def test_cancellation_cleans_hook_approval(harness):
    settings, store, _, runtime, session = harness
    runtime.provider = ToolSequence()
    async def scenario():
        runtime.start(session, 'write')
        run = runtime.active[session]
        await wait_for_approval(runtime, session)
        await runtime.stop(session)
        assert run.approvals == {}
    asyncio.run(scenario())
    assert not (settings.workspace / 'approval_test.py').exists()
    assert any(event['type'] == 'approval_result' and event.get('reason') == 'cancelled' for event in store.events(session))
