from fastapi.testclient import TestClient
from app import create_app
from ecoder.runtime import Run
from ecoder.store import Store
from test_harness import harness


def test_user_can_edit_persist_and_clear_session_memory(harness):
    settings,*_=harness;app=create_app(settings)
    with TestClient(app) as client:
        session=client.post('/api/sessions').json()['id'];url=f'/api/sessions/{session}/memory'
        assert client.get(url).json()=={'memory':''}
        content='用户偏好：使用 PowerShell\n约束：不修改测试文件'
        result=client.put(url,json={'content':content,'expected':''})
        assert result.status_code==200 and result.json()['memory']==content
        assert client.get(f'/api/sessions/{session}').json()['memory']==content
        assert content in app.state.runtime.system(session)['content']
        assert Store(app.state.store.path).memory(session)==content
        assert client.put(url,json={'content':'','expected':content}).status_code==200
        assert client.get(url).json()['memory']==''


def test_edit_rejects_stale_or_running_updates_and_preserves_latest_memory(harness):
    settings,*_=harness;app=create_app(settings)
    with TestClient(app) as client:
        session=client.post('/api/sessions').json()['id'];other=client.post('/api/sessions').json()['id'];url=f'/api/sessions/{session}/memory'
        app.state.store.save_memory(session,'Agent 的最新记录')
        response=client.put(url,json={'content':'旧页面的草稿','expected':''})
        assert response.status_code==409 and '已被更新' in response.json()['detail']
        assert client.get(url).json()['memory']=='Agent 的最新记录'
        assert client.get(f'/api/sessions/{other}/memory').json()['memory']==''
        app.state.runtime.active[session]=Run()
        assert client.put(url,json={'content':'新内容','expected':'Agent 的最新记录'}).status_code==409
        app.state.runtime.active.clear()
        assert client.put(url,json={'content':'x'*8001,'expected':'Agent 的最新记录'}).status_code==422
        assert client.put('/api/sessions/missing/memory',json={'content':'x','expected':''}).status_code==404
