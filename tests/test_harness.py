import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from ecoder.config import ROOT, Settings
from ecoder.context import build_context
from ecoder.provider import Provider
from ecoder.runtime import Runtime
from ecoder.skills import Skills
from ecoder.store import Store
from ecoder.tools import Tools


@pytest.fixture
def harness(tmp_path):
    settings = Settings(root=tmp_path, workspace=tmp_path / "workspace")
    shutil.copytree(ROOT / "skills", tmp_path / "skills")
    shutil.copytree(ROOT / "static", tmp_path / "static")
    store = Store(tmp_path / "state.db")
    skills = Skills(tmp_path / "skills")
    tools = Tools(settings.workspace, store, skills)
    runtime = Runtime(settings, store, tools, skills)
    session = store.create_session()["id"]
    return settings, store, tools, runtime, session


def test_path_and_secret_boundaries(harness):
    settings, _, tools, _, _ = harness
    for path in ("../outside.txt", str(settings.root / "outside.txt"), ".env", ".env.local", ".ENV", ".GIT/config"):
        with pytest.raises(ValueError):
            tools.path(path)
    assert tools.path("src/main.py").is_relative_to(settings.workspace)


def test_symlink_escape(harness):
    settings, _, tools, _, _ = harness
    try:
        (settings.workspace / "escape").symlink_to(settings.root, target_is_directory=True)
    except OSError:
        pytest.skip("Windows 未授予创建符号链接权限")
    with pytest.raises(ValueError):
        tools.path("escape/outside.txt")


def test_approval_snapshot_rejects_changed_file(harness):
    settings, _, tools, _, session = harness
    target = settings.workspace / "file.py"
    target.write_text("before", encoding="utf-8")
    args = {"path": "file.py", "content": "after"}
    snapshot = tools.preview("write_file", args)
    target.write_text("external change", encoding="utf-8")
    with pytest.raises(ValueError, match="审批期间"):
        asyncio.run(tools.execute(session, "write_file", args, snapshot))
    assert target.read_text(encoding="utf-8") == "external change"


def test_write_and_command_cannot_bypass_approval(harness):
    _, _, tools, _, session = harness
    for name, args in [("write_file", {"path": "x", "content": "x"}), ("run_command", {"argv": [sys.executable, "-V"], "timeout": 5})]:
        with pytest.raises(ValueError, match="审批"):
            asyncio.run(tools.execute(session, name, args))


def test_dependency_and_session_isolation(harness):
    _, store, tools, _, session = harness
    async def scenario():
        first = await tools.execute(session, "create_task", {"title": "first", "dependencies": []})
        second = await tools.execute(session, "create_task", {"title": "second", "dependencies": [first["id"]]})
        with pytest.raises(ValueError, match="依赖尚未完成"):
            await tools.execute(session, "update_task", {"id": second["id"], "status": "completed"})
        other = store.create_session()["id"]
        with pytest.raises(ValueError):
            await tools.execute(other, "update_task", {"id": first["id"], "status": "completed"})
        await tools.execute(session, "update_task", {"id": first["id"], "status": "completed"})
        await tools.execute(session, "update_task", {"id": second["id"], "status": "in_progress"})
        with pytest.raises(ValueError, match="回退"):
            await tools.execute(session, "update_task", {"id": first["id"], "status": "pending"})
    asyncio.run(scenario())


def test_compaction_preserves_tool_pairs_and_original():
    history = []
    for i in range(4):
        history += [{"role": "user", "content": str(i)}, {"role": "assistant", "content": None, "tool_calls": [{"id": str(i)}]}, {"role": "tool", "tool_call_id": str(i), "content": "x"*5000}, {"role": "assistant", "content": "done"}]
    original = json.dumps(history)
    messages, stats = build_context(history, 7000)
    calls = {call["id"] for m in messages for call in m.get("tool_calls", [])}
    results = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    assert calls == results
    assert messages[0]["role"] == "user"
    assert stats["before_chars"] > stats["after_chars"]
    assert json.dumps(history) == original
    assert messages[-2]["content"] == "x"*5000  # current turn is not truncated


class ToolSequence:
    async def stream(self, messages, tools):
        start = max(i for i, message in enumerate(messages) if message["role"] == "user")
        results = [m for m in messages[start:] if m["role"] == "tool"]
        if not results:
            call = {"id": "write_1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "approval_test.py", "content": "value = 42\n"})}}
            yield {"type": "response", "message": {"role": "assistant", "content": None, "tool_calls": [call]}}
        else:
            content = "操作已处理"
            yield {"type": "text_delta", "content": content}
            yield {"type": "response", "message": {"role": "assistant", "content": content}}


async def wait_for_approval(runtime, session):
    for _ in range(250):
        pending = runtime.pending(session)
        if pending:
            return pending[0]
        await asyncio.sleep(0.01)
    raise AssertionError("审批事件未出现")


@pytest.mark.parametrize("allow", [True, False])
def test_end_to_end_approval(harness, allow):
    settings, store, _, runtime, session = harness
    async def scenario():
        runtime.provider = ToolSequence()
        runtime.start(session, "写入文件")
        worker = runtime.active[session].task
        with pytest.raises(ValueError, match="运行中"):
            runtime.start(session, "concurrent")
        approval = await wait_for_approval(runtime, session)
        target = settings.workspace / "approval_test.py"
        assert not target.exists()
        runtime.approve(session, approval["approval_id"], allow)
        await asyncio.wait_for(worker, 5)
        assert target.exists() is allow
        events = store.events(session)
        assert events[-1]["type"] == "run_end"
        assert events[-1]["status"] == "completed"
        assert store.messages(session)[-1]["content"] == "操作已处理"
        assert any(e["type"] == "approval_result" and e["allowed"] is allow for e in events)
        assert session not in runtime.active
        restored = Store(store.path)
        assert restored.messages(session) == store.messages(session)
    asyncio.run(scenario())


def test_cancel_preserves_tool_protocol(harness):
    settings, store, _, runtime, session = harness
    async def scenario():
        runtime.provider = ToolSequence()
        runtime.start(session, "写入文件")
        await wait_for_approval(runtime, session)
        await runtime.stop(session)
        assert not (settings.workspace / "approval_test.py").exists()
        history = store.messages(session)
        calls = {c["id"] for m in history for c in m.get("tool_calls", [])}
        results = {m["tool_call_id"] for m in history if m["role"] == "tool"}
        assert calls == results
        assert store.events(session)[-1]["status"] == "cancelled"
        assert runtime.pending(session) == []
    asyncio.run(scenario())


def test_command_exit_code_and_timeout(harness):
    _, _, tools, _, _ = harness
    async def scenario():
        result = await tools.command({"argv": [sys.executable, "-c", "print('verified');raise SystemExit(3)"], "timeout": 5})
        assert result["exit_code"] == 3
        assert "verified" in result["output"]
        with pytest.raises(TimeoutError):
            await tools.command({"argv": [sys.executable, "-c", "import time; time.sleep(20)"], "timeout": 1})
    asyncio.run(scenario())


def test_http_validation_and_origin_boundary(harness):
    settings, *_ = harness
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        status = client.get("/api/status").json()
        assert len(status["tools"]) == 15
        assert any(tool["name"] == "sub_agent" for tool in status["tools"])
        assert "api_key" not in status
        session = client.post("/api/sessions").json()["id"]
        assert client.post(f"/api/sessions/{session}/runs", json={"message":"   "}).status_code == 422
        assert client.post("/api/sessions", headers={"Origin":"https://evil.example"}).status_code == 403
        assert client.get("/api/status", headers={"Host":"evil.example"}).status_code == 403
        assert client.get("/api/sessions/missing").status_code == 404
        assert client.post(f"/api/sessions/{session}/approvals/missing",json={"allow":True}).status_code == 409


def test_provider_streamed_tool_fragments(harness, monkeypatch):
    import httpx
    settings, *_ = harness
    settings.mode, settings.api_key = "live", "unit-test-placeholder"
    chunks = [
        {"choices":[{"delta":{"reasoning_content":"provider-specific context"}}]},
        {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"read_","arguments":'{"path":'}}]}}]},
        {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":'"main.py"}'}}]}}]},
        {"choices":[{"delta":{},"finish_reason":"tool_calls"}]},
    ]
    body = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    async def scenario():
        events = [e async for e in Provider(settings).stream([{"role":"user","content":"test"}], [])]
        call = events[-1]["message"]["tool_calls"][0]
        assert events[-1]["message"]["reasoning_content"] == "provider-specific context"
        assert call["id"] == "call_1"
        assert call["function"] == {"name":"read_file","arguments":'{"path":"main.py"}'}
    asyncio.run(scenario())


def test_archive_preserves_legacy_history(harness):
    _, store, _, _, session = harness
    store.event(session, "run_start", mode="demo")
    store.append(session, {"role":"user", "content":"legacy input"})
    live = store.create_session()["id"]
    store.event(live, "run_start", mode="live")
    store.archive_legacy_runs()
    assert session not in {s["id"] for s in store.sessions()}
    assert live in {s["id"] for s in store.sessions()}
    assert store.messages(session)[0]["content"] == "legacy input"


def test_production_ui_has_no_canned_prompts():
    sources = ROOT / "frontend" / "src"
    source = "\n".join(path.read_text(encoding="utf-8") for path in sources.rglob("*")
                       if path.suffix in {".vue", ".js"} and not path.name.endswith(".test.js"))
    assert "演示" not in source
    assert "固定示例" not in source
    index = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "/static/vue/assets/" in index
    assert "/static/app.js" not in index


def test_config_save_apply_and_keep_key(harness, monkeypatch):
    from dotenv import dotenv_values
    import ecoder.config as configuration
    settings, *_ = harness
    env_file = settings.root / ".env"
    env_file.write_text("# existing comment\nECODER_WORKSPACE=./my-project\nCUSTOM_FLAG=preserve\n", encoding="utf-8")
    application = create_app(settings)
    secret = "test-credential-only-not-real"
    with TestClient(application) as client:
        result = client.post("/api/config", json={"base_url":"https://models.example/v1/", "model":"test-model", "api_key":secret})
        assert result.status_code == 200
        assert secret not in result.text
        assert result.json()["configured"] is True
        runtime = application.state.runtime
        assert runtime.settings.api_key == secret
        assert runtime.provider.settings is runtime.settings
        assert runtime.learning.provider.settings is runtime.settings
        assert runtime.settings.base_url == "https://models.example/v1"
        for endpoint in ("/api/config", "/api/status"):
            response = client.get(endpoint)
            assert secret not in response.text
            assert "api_key" not in response.json()
        result = client.post("/api/config", json={"base_url":"http://127.0.0.1:9000/v1", "model":"second-model", "api_key":""})
        assert result.status_code == 200
        assert runtime.settings.api_key == secret
        assert runtime.settings.model == "second-model"
        assert client.get("/api/config").headers["cache-control"] == "no-store"
    values = dotenv_values(env_file)
    assert values["ECODER_API_KEY"] == secret
    assert values["CUSTOM_FLAG"] == "preserve"
    assert "# existing comment" in env_file.read_text(encoding="utf-8")
    monkeypatch.setattr(configuration, "ROOT", settings.root)
    monkeypatch.setenv("ECODER_API_KEY", "stale-environment-value")
    assert configuration.Settings.load().api_key == secret
    assert configuration.Settings.load().model == "second-model"


@pytest.mark.parametrize("patch", [
    {"base_url":"http://untrusted.example/v1"},
    {"base_url":"https://user:password@example.com/v1"},
    {"base_url":"https://example.com/v1?api_key=secret"},
    {"model":"  "},
    {"api_key":"private-input\nforbidden"},
    {"api_key":{"invalid":"private-input"}},
])
def test_config_invalid_input_is_not_echoed(harness, patch):
    settings, *_ = harness
    with TestClient(create_app(settings)) as client:
        body = {"base_url":"https://models.example/v1", "model":"test-model", "api_key":"private-input"}
        body.update(patch)
        response = client.post("/api/config", json=body)
        assert response.status_code == 422
        assert "private-input" not in response.text
        assert "input" not in response.json()
        assert not (settings.root / ".env").exists()


def test_config_busy_origin_and_atomic_failure(harness, monkeypatch):
    import ecoder.config as configuration
    settings, *_ = harness
    original = "CUSTOM_FLAG=original\n"
    env_file = settings.root / ".env"
    env_file.write_text(original, encoding="utf-8")
    application = create_app(settings)
    body = {"base_url":"https://models.example/v1", "model":"test-model", "api_key":"private-input"}
    with TestClient(application) as client:
        assert client.post("/api/config", json=body, headers={"Origin":"https://other.example"}).status_code == 403
        application.state.runtime.active["busy"] = object()
        try:
            assert client.post("/api/config", json=body).status_code == 409
        finally:
            application.state.runtime.active.clear()
        def fail_replace(*args):
            raise OSError("write unavailable")
        monkeypatch.setattr(configuration.os, "replace", fail_replace)
        response = client.post("/api/config", json=body)
        assert response.status_code == 500
        assert "private-input" not in response.text
        assert env_file.read_text(encoding="utf-8") == original
        assert application.state.runtime.settings.api_key == ""
        assert not list(settings.root.glob(".ecoder-config-*.tmp"))


def test_permanent_delete_removes_all_related_rows(harness):
    settings, *_ = harness
    application=create_app(settings)
    store=application.state.store
    session=store.create_session("Delete this conversation")["id"]
    other=store.create_session("Keep this conversation")["id"]
    for sid in (session,other):
        store.append(sid,{"role":"user","content":"stored history"})
        store.event(sid,"run_end",status="completed")
        store.save_task(sid,{"id":sid,"title":"task","status":"completed","dependencies":[]})
        store.save_memory(sid,"stored memory")
    code=settings.workspace/"keep.py"
    code.write_text("value = 1\n",encoding="utf-8")
    with TestClient(application) as client:
        response=client.delete(f"/api/sessions/{session}")
        assert response.status_code==200
        assert response.json()["recoverable"] is False
        assert client.get(f"/api/sessions/{session}").status_code==404
        assert client.post(f"/api/sessions/{session}/runs",json={"message":"cannot run"}).status_code==404
        assert client.post(f"/api/sessions/{session}/restore").status_code==404
        assert client.delete(f"/api/sessions/{session}").status_code==404
    persisted=Store(store.path)
    assert not persisted.exists(session)
    assert persisted.exists(other)
    with persisted.connect() as db:
        assert db.execute("SELECT count(*) FROM sessions WHERE id=?",(session,)).fetchone()[0]==0
        for table in ("messages","events","tasks","memories"):
            assert db.execute(f"SELECT count(*) FROM {table} WHERE session=?",(session,)).fetchone()[0]==0
            assert db.execute(f"SELECT count(*) FROM {table} WHERE session=?",(other,)).fetchone()[0]==1
    assert code.read_text(encoding="utf-8")=="value = 1\n"


def test_delete_busy_missing_and_cross_origin(harness):
    settings, *_ = harness
    application=create_app(settings)
    with TestClient(application) as client:
        session=client.post("/api/sessions").json()["id"]
        assert client.delete("/api/sessions/missing").status_code==404
        assert client.delete(f"/api/sessions/{session}",headers={"Origin":"https://other.example"}).status_code==403
        application.state.runtime.active[session]=object()
        try:
            assert client.delete(f"/api/sessions/{session}").status_code==409
            assert application.state.store.exists(session)
        finally:
            application.state.runtime.active.clear()
        assert client.delete(f"/api/sessions/{session}").status_code==200
        assert not application.state.store.sessions()


def test_legacy_soft_deleted_rows_are_purged(harness):
    _,store,*_=harness
    removed=store.create_session("Previously deleted")["id"]
    kept=store.create_session("Keep active record")["id"]
    store.append(removed,{"role":"user","content":"remove history"})
    store.event(removed,"run_end",status="completed")
    store.save_task(removed,{"id":removed,"title":"remove","status":"completed","dependencies":[]})
    store.save_memory(removed,"remove memory")
    with store.connect() as db:
        db.execute("ALTER TABLE sessions ADD COLUMN deleted_at REAL")
        db.execute("UPDATE sessions SET deleted_at=1 WHERE id=?",(removed,))
    migrated=Store(store.path)
    assert not migrated.exists(removed)
    assert migrated.exists(kept)
    with migrated.connect() as db:
        assert "deleted_at" not in {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
        for table in ("messages","events","tasks","memories"):
            assert db.execute(f"SELECT count(*) FROM {table} WHERE session=?",(removed,)).fetchone()[0]==0


def test_permanent_delete_is_transactional(harness):
    import sqlite3
    _,store,_,_,session=harness
    store.append(session,{"role":"user","content":"keep on failure"})
    store.event(session,"run_end",status="completed")
    with store.connect() as db:
        db.execute("CREATE TRIGGER reject_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.delete_session(session)
    assert store.exists(session)
    assert len(store.messages(session))==1
    assert len(store.events(session))==1

