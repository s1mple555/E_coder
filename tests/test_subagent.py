import asyncio
import copy
import json
import sys

import pytest

from test_harness import harness, wait_for_approval
from ecoder.tools import SUBAGENT_TOOLS
from test_uploads import uploaded_app, send_files
from test_local_folders import connect


def tool_call(name, args, call_id="same-id"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class DelegationSequence:
    def __init__(self, action="read_file", args=None, repeat=False, fail=False):
        self.action = action
        self.args = args if args is not None else {"path": "sample.txt"}
        self.repeat, self.fail = repeat, fail
        self.requests = []

    async def stream(self, messages, tools):
        names = {tool["function"]["name"] for tool in tools}
        self.requests.append((copy.deepcopy(messages), names))
        results = [message for message in messages if message["role"] == "tool"]
        if "sub_agent" in names:
            if not results:
                message = {"role": "assistant", "content": None, "tool_calls": [tool_call("sub_agent", {"prompt": "Inspect sample.txt; return a short finding."})]}
            else:
                message = {"role": "assistant", "content": "parent final"}
                yield {"type": "text_delta", "content": "parent final"}
        else:
            if self.fail:
                raise RuntimeError("remote-secret-must-not-leak")
            if not results or self.repeat:
                message = {"role": "assistant", "content": None, "tool_calls": [tool_call(self.action, self.args)]}
            else:
                message = {"role": "assistant", "content": "child final"}
                yield {"type": "text_delta", "content": "child final"}
        yield {"type": "usage", "total_tokens": 10}
        yield {"type": "response", "message": message}


def prepare(harness, provider):
    settings, store, _, runtime, session = harness
    (settings.workspace / "sample.txt").write_text("private intermediate file contents", encoding="utf-8")
    runtime.provider = provider
    return settings, store, runtime, session


def test_delegation_isolates_history_and_returns_only_final_summary(harness):
    provider = DelegationSequence()
    _, store, runtime, session = prepare(harness, provider)
    store.save_memory(session, "parent-only-memory")
    store.append(session, {"role": "user", "content": "parent-only-history"})

    async def scenario():
        runtime.start(session, "delegate this task")
        await asyncio.wait_for(runtime.active[session].task, 5)
    asyncio.run(scenario())
    child_requests = [messages for messages, names in provider.requests if "sub_agent" not in names]
    assert len(child_requests) == 2
    assert len(child_requests[0]) == 2  # system + explicit subtask only
    assert "parent-only-history" not in json.dumps(child_requests)
    assert "parent-only-memory" not in json.dumps(child_requests)
    assert all(names == SUBAGENT_TOOLS for _, names in provider.requests if "sub_agent" not in names)
    assert "private intermediate file contents" in json.dumps(child_requests)
    history = store.messages(session)
    assert "private intermediate file contents" not in json.dumps(history)
    assert "read_file" not in json.dumps(history)
    result = json.loads(next(message["content"] for message in history if message["role"] == "tool"))
    assert result["summary"] == "child final" and result["status"] == "completed"
    assert history[-1]["content"] == "parent final"
    events = store.events(session)
    assert [event["content"] for event in events if event["type"] == "text_delta"] == ["parent final"]
    assert any(event["type"] == "subagent_text_delta" for event in events)
    starts = [event for event in events if event["type"] == "tool_start"]
    assert len({event["call_id"] for event in starts}) == 2
    assert starts[1]["parent_call_id"] == starts[0]["call_id"]
    assert all(event["run_id"] == events[0]["run_id"] for event in events)
    assert len([event for event in events if event["type"] == "step_start"]) == 4
    assert events[-1]["status"] == "completed"


@pytest.mark.parametrize("name,args", [
    ("sub_agent", {"prompt": "recurse"}),
    ("save_memory", {"content": "overwrite"}),
    ("create_task", {"title": "unwanted"}),
    ("unknown_tool", {}),
])
def test_subagent_cannot_recurse_or_mutate_parent_state(harness, name, args):
    _, store, runtime, session = prepare(harness, DelegationSequence(name, args))
    store.save_memory(session, "keep")

    async def scenario():
        runtime.start(session, "delegate")
        await asyncio.wait_for(runtime.active[session].task, 5)
    asyncio.run(scenario())
    events = store.events(session)
    assert len([event for event in events if event["type"] == "subagent_start"]) == 1
    assert any("不允许" in event.get("result", {}).get("error", "") for event in events if event["type"] == "tool_end")
    assert store.memory(session) == "keep" and store.tasks(session) == []


@pytest.mark.parametrize("allow", [True, False])
@pytest.mark.parametrize("action,args", [
    ("write_file", {"path": "child.txt", "content": "approved child write"}),
    ("run_command", {"argv": [sys.executable, "-c", "from pathlib import Path; Path('child.txt').write_text('approved child command')"], "timeout": 5}),
])
def test_subagent_writes_and_commands_require_existing_approval(harness, allow, action, args):
    settings, store, runtime, session = prepare(harness, DelegationSequence(action, args))

    async def scenario():
        runtime.start(session, "delegate")
        worker = runtime.active[session].task
        approval = await wait_for_approval(runtime, session)
        assert approval["name"] == action
        assert not (settings.workspace / "child.txt").exists()
        runtime.approve(session, approval["approval_id"], allow)
        await asyncio.wait_for(worker, 10)
    asyncio.run(scenario())
    assert (settings.workspace / "child.txt").exists() is allow
    events = store.events(session)
    request = next(event for event in events if event["type"] == "approval_request")
    assert request["subagent_id"] and request["parent_call_id"]
    assert any(event["type"] == "approval_result" and event["allowed"] is allow for event in events)


def test_stop_cancels_subagent_and_clears_approvals(harness):
    settings, store, runtime, session = prepare(harness, DelegationSequence("write_file", {"path": "child.txt", "content": "no"}))

    async def scenario():
        runtime.start(session, "delegate")
        await wait_for_approval(runtime, session)
        await runtime.stop(session)
    asyncio.run(scenario())
    assert not (settings.workspace / "child.txt").exists()
    assert session not in runtime.active and runtime.pending(session) == []
    events = store.events(session)
    assert next(event for event in events if event["type"] == "subagent_end")["status"] == "cancelled"
    assert events[-1]["status"] == "cancelled"
    history = store.messages(session)
    assert {call["id"] for message in history for call in message.get("tool_calls", [])} == {message["tool_call_id"] for message in history if message["role"] == "tool"}
    assert {event["call_id"] for event in events if event["type"] == "tool_start"} == {event["call_id"] for event in events if event["type"] == "tool_end"}


def test_subagent_limit_is_reported_as_incomplete(harness):
    _, store, runtime, session = prepare(harness, DelegationSequence(repeat=True))
    runtime.settings.max_steps = 2

    async def scenario():
        runtime.start(session, "delegate")
        await asyncio.wait_for(runtime.active[session].task, 5)
    asyncio.run(scenario())
    result = json.loads(next(message["content"] for message in store.messages(session) if message["role"] == "tool"))
    assert result["status"] == "limit_reached" and result["steps"] == 2
    assert "error" in result and "summary" not in result


def test_subagent_provider_failure_does_not_leak_remote_errors(harness):
    _, store, runtime, session = prepare(harness, DelegationSequence(fail=True))

    async def scenario():
        runtime.start(session, "delegate")
        await asyncio.wait_for(runtime.active[session].task, 5)
    asyncio.run(scenario())
    result = json.loads(next(message["content"] for message in store.messages(session) if message["role"] == "tool"))
    assert "error" in result and "RuntimeError" in result["error"]
    assert "remote-secret" not in json.dumps(store.events(session))
    assert next(event for event in store.events(session) if event["type"] == "subagent_end")["status"] == "failed"


def test_subagent_rejects_outside_workspace_and_oversized_context(harness):
    _, store, runtime, session = prepare(harness, DelegationSequence("read_file", {"path": "../outside.txt"}))

    async def scenario():
        runtime.start(session, "delegate")
        await asyncio.wait_for(runtime.active[session].task, 5)
    asyncio.run(scenario())
    assert any("工作区边界" in event.get("result", {}).get("error", "") for event in store.events(session) if event["type"] == "tool_end")
    runtime.settings.context_chars = 1

    async def oversized():
        from ecoder.runtime import Run
        result = await runtime.invoke(session, Run(), tool_call("sub_agent", {"prompt": "large"}))
        assert "上下文过大" in result["error"]
    asyncio.run(oversized())


@pytest.mark.parametrize("args", [{"prompt": ""}, {"prompt": "   "}, {"prompt": "x", "max_steps": 31}, {"prompt": "x", "max_steps": 0}])
def test_invalid_delegation_arguments(harness, args):
    _, _, tools, _, _ = harness
    with pytest.raises(ValueError):
        tools.validate("sub_agent", args)


def test_subagent_uses_connected_folder_and_explicit_attachment_access(uploaded_app, tmp_path):
    application, client, session = uploaded_app
    record = send_files(client, session, [("attachment.txt", b"allowed attachment", "text/plain")]).json()["files"][0]
    project = tmp_path / "connected"
    project.mkdir()
    (project / "sample.txt").write_text("connected workspace", encoding="utf-8")
    assert connect(client, session, project).status_code == 200
    runtime = application.state.runtime
    attachment = runtime.uploads.attachment_path(session, record["id"])

    async def scenario():
        for path, expected in [("sample.txt", "connected workspace"), (str(attachment), "allowed attachment")]:
            provider = DelegationSequence("read_file", {"path": path})
            runtime.provider = provider
            from ecoder.runtime import Run
            result = await runtime.run_subagent(session, Run(), "delegate", "Read the given file")
            assert result["status"] == "completed"
            assert expected in json.dumps([messages for messages, _ in provider.requests])
        other = client.post('/api/sessions').json()['id']
        runtime.provider = DelegationSequence("read_file", {"path": str(attachment)})
        await runtime.run_subagent(other, Run(), "other", "Read file")
        assert any("工作区边界" in event.get("result", {}).get("error", "") for event in application.state.store.events(other) if event["type"] == "tool_end")
    asyncio.run(scenario())
