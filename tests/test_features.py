import asyncio,json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import create_app
from test_harness import harness

class Reflector:
    def __init__(self,evidence):self.evidence=evidence;self.requests=[]
    async def stream(self,messages,tools):
        self.requests.append(messages)
        assert tools==[]
        yield {'type':'response','message':{'content':json.dumps({'lessons':[{'title':'Python 文件写入验证','when':'Python 文件写入','strategy':'写入后读回并比较内容，保留验证证据。','evidence':[self.evidence]}]})}}

def seed(store,session):
    store.event(session,'user_message',run_id='r',content='Python 文件写入')
    store.event(session,'run_start',run_id='r')
    event=store.event(session,'tool_end',run_id='r',name='read_file',result={'text':'verified'})
    store.event(session,'run_end',run_id='r',status='completed')
    return event['seq']

def test_reflection_dedup_retrieval_and_toggle(harness):
    _,store,_,runtime,session=harness
    evidence=seed(store,session);runtime.learning.provider=Reflector(evidence)
    with pytest.raises(ValueError):asyncio.run(runtime.learning.extract(session,'r',False))
    rows=asyncio.run(runtime.learning.extract(session,'r',True))
    assert len(rows)==1 and rows[0]['confirmations']==1
    assert len(asyncio.run(runtime.learning.extract(session,'r',True)))==1
    store.append(session,{'role':'user','content':'Python 文件写入'})
    assert '写入后读回' in runtime.learning.context(session)
    runtime.learning.update(session,rows[0]['id'],False)
    assert runtime.learning.context(session)==''
    assert runtime.learning.provider.requests

def test_invalid_citations_save_nothing(harness):
    _,store,_,runtime,session=harness;seed(store,session)
    runtime.learning.provider=Reflector(999999)
    with pytest.raises(ValueError):asyncio.run(runtime.learning.extract(session,'r',True))
    assert runtime.learning.list(session)==[]

def test_failed_runs_cannot_be_learned(harness):
    _,store,_,runtime,session=harness
    store.event(session,'run_start',run_id='bad');store.event(session,'run_end',run_id='bad',status='failed')
    with pytest.raises(ValueError):asyncio.run(runtime.learning.extract(session,'bad',True))

def test_preview_assets_annotations_and_stale_revision(harness):
    settings,_,_,_,_=harness
    with TestClient(create_app(settings)) as client:
        session=client.post('/api/sessions').json()['id'];prefix=f'/api/sessions/{session}'
        root=client.app.state.runtime.uploads.workspace(session);root.mkdir(parents=True,exist_ok=True)
        (root/'index.html').write_text('<h1 data-component="Hero">Hi</h1><script src="/main.js"></script>',encoding='utf-8')
        (root/'main.js').write_text('console.log("hello")')
        (root/'.env').write_text('secret')
        data=client.post(prefix+'/preview',json={'entry':'index.html'}).json()
        page=client.get(data['url']);assert page.status_code==200
        assert 'sandbox allow-scripts' in page.headers['content-security-policy']
        assert 'ecoder:annotation' in page.text
        assert client.get(prefix+f"/preview/assets/{data['token']}/main.js").status_code==200
        assert client.get(prefix+f"/preview/assets/{data['token']}/.env").status_code==404
        assert client.get(prefix+'/preview/document/invalid').status_code==404
        second=client.post('/api/sessions').json()['id']
        assert client.get(f"/api/sessions/{second}/preview/document/{data['token']}").status_code==404
        body={'entry':'index.html','revision':data['revision'],'selector':'h1','text':'Hi','note':'改成蓝色','rect':{'x':0,'y':0,'width':100,'height':30},'viewport':{'width':1200,'height':800}}
        saved=client.post(prefix+'/annotations',json=body);assert saved.status_code==200,saved.text
        assert client.get(prefix+'/annotations').json()['annotations'][0]['note']=='改成蓝色'
        (root/'index.html').write_text('changed')
        assert client.post(prefix+'/annotations/submit',json={'ids':[saved.json()['id']]}).status_code==409
        assert client.post(prefix+'/annotations',json=body).status_code==400

def test_annotation_submit_uses_runtime_and_permission(harness,monkeypatch):
    from ecoder.preview import Preview
    _,_,tools,runtime,session=harness;(tools.root/'index.html').write_text('<button>Go</button>')
    preview=Preview(runtime);item=preview.save(session,{'entry':'index.html','revision':preview.digest(session,'index.html'),'selector':'button','note':'修改颜色'})
    captured=[];monkeypatch.setattr(runtime,'start',lambda s,m:captured.append((s,m)) or 'run')
    assert preview.submit(session,[item['id']])=={'run_id':'run'}
    assert '修改颜色' in captured[0][1] and '仍需审批' in captured[0][1]
    assert preview.list(session)[0]['status']=='submitted'
    with pytest.raises(ValueError):preview.submit(session,[item['id']])


def test_annotation_endpoint_starts_on_event_loop(harness):
    settings,_,_,_,_=harness
    class NoTools:
        async def stream(self,*args):
            yield {'type':'response','message':{'role':'assistant','content':'Synthetic run done'}}
    with TestClient(create_app(settings)) as client:
        session=client.post('/api/sessions').json()['id'];prefix=f'/api/sessions/{session}'
        runtime=client.app.state.runtime;runtime.provider=NoTools()
        root=runtime.uploads.workspace(session);root.mkdir(exist_ok=True,parents=True)
        (root/'index.html').write_text('<h1>Preview</h1>')
        data=client.post(prefix+'/preview',json={'entry':'index.html'}).json()
        body={'entry':'index.html','revision':data['revision'],'selector':'h1','note':'修改标题','rect':{'x':0,'y':0,'width':10,'height':10},'viewport':{'width':100,'height':100}}
        identifier=client.post(prefix+'/annotations',json=body).json()['id']
        response=client.post(prefix+'/annotations/submit',json={'ids':[identifier]})
        assert response.status_code==200,response.text
        assert response.json()['run_id']
        assert client.get(prefix+'/annotations').json()['annotations'][0]['status']=='submitted'


def test_project_scope_and_restart(harness,tmp_path):
    from ecoder.learning import Learning
    _,store,tools,runtime,session=harness
    runtime.learning.provider=Reflector(seed(store,session))
    rows=asyncio.run(runtime.learning.extract(session,'r',True))
    assert Learning(runtime).list(session)[0]['id']==rows[0]['id']
    old=tools.root;tools.root=tmp_path/'different';tools.root.mkdir()
    assert runtime.learning.list(session)==[]
    with pytest.raises(ValueError):runtime.learning.update(session,rows[0]['id'],False)
    tools.root=old
