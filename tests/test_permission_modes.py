import asyncio
import sys

from fastapi.testclient import TestClient
from app import create_app
from ecoder.config import Settings, save_model_settings
from ecoder.runtime import Run
from test_harness import harness
from test_subagent import tool_call


def test_full_mode_writes_without_approval_and_keeps_audit(harness):
    settings, store, _, runtime, session = harness
    settings.permission_mode = "full"
    result = asyncio.run(runtime.invoke(session, Run(), tool_call("write_file", {"path":"auto.txt","content":"ok"})))
    assert "error" not in result
    assert (settings.workspace / "auto.txt").read_text() == "ok"
    events = store.events(session)
    assert any(e["type"] == "permission_auto_allow" for e in events)
    assert not any(e["type"] == "approval_request" for e in events)


def test_full_mode_host_command_overrides_sandbox(harness):
    settings, store, tools, runtime, session = harness
    settings.permission_mode = "full"
    result = asyncio.run(runtime.invoke(session, Run(), tool_call("run_command", {
        "argv":[sys.executable,"-c","print('AUTO_HOST_OK')"],"execution_mode":"sandbox"})))
    assert "error" not in result
    assert "AUTO_HOST_OK" in str(result)
    event = next(e for e in store.events(session) if e["type"] == "permission_auto_allow")
    assert event["arguments"]["execution_mode"] == "host"


def test_full_mode_preserves_validation_and_child_whitelist(harness):
    settings, _, _, runtime, session = harness
    settings.permission_mode = "full"
    result = asyncio.run(runtime.invoke(session, Run(), tool_call("write_file", {"path":"../outside.txt","content":"bad"})))
    assert "error" in result
    from ecoder.tools import SUBAGENT_TOOLS
    result = asyncio.run(runtime.invoke(session, Run(), tool_call("create_task", {"title":"bad"}), allowed_tools=SUBAGENT_TOOLS))
    assert "error" in result


def test_permission_api_persists_rejects_invalid_and_running(harness):
    settings, _, _, _, _ = harness
    settings.api_key = "test-only-key"
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/status").json()["permission_mode"] == "approval"
        assert client.post("/api/permissions",json={"permission_mode":"invalid"}).status_code == 422
        assert client.post("/api/permissions",json={"permission_mode":"full"}).status_code == 200
        assert 'ECODER_PERMISSION_MODE=\'full\'' in (settings.root / ".env").read_text()
        status=client.get("/api/status").json()
        assert status["permission_mode"] == "full"
        assert status["sandbox"]["default_mode"] == "host"
        updated=save_model_settings(app.state.runtime.settings,base_url=settings.base_url,model="another-model")
        assert updated.permission_mode == "full" and updated.api_key == "test-only-key"
        app.state.runtime.active["busy"] = Run()
        assert client.post("/api/permissions",json={"permission_mode":"approval"}).status_code == 409
        app.state.runtime.active.clear()
        assert client.post("/api/permissions",json={"permission_mode":"approval"}).status_code == 200
        assert client.get("/api/status").json()["sandbox"]["default_mode"] == "sandbox"
