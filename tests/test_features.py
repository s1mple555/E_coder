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


def test_reflection_context_preserves_evidence_and_json_for_long_traces():
    from ecoder.learning import reflection_context
    trace=[{'type':'user_message','content':'诊断检索流程 token=hidden-value'}]
    for index in range(9):
        trace.append({'type':'tool_end','seq':index+10,'name':'run_command','result':{'exit_code':0,'output':'key-value-to-redact '+('DATA '*15000)}})
    trace.extend({'type':'text_delta','content':'最终结果'} for _ in range(2000))
    text,evidence=reflection_context(trace,'key-value-to-redact')
    document=json.loads(text)
    assert len(text)<=24000
    assert evidence==set(range(10,19))
    assert set(document['allowed_success_evidence'])==evidence
    assert {item['seq'] for item in document['tools']}==evidence
    assert 'key-value-to-redact' not in text and 'hidden-value' not in text
    assert document['task'].startswith('诊断检索流程')


@pytest.mark.parametrize('failure,expected_status,expected_text',[
    ('json',400,'不是有效 JSON'),('citation',400,'工具证据'),
    ('timeout',504,'超时'),('network',502,'无法连接模型服务'),('fields',400,'字段或长度')])
def test_extraction_reports_specific_safe_error(harness,failure,expected_status,expected_text):
    import httpx
    settings,_,_,_,_=harness
    class BrokenReflector:
        async def stream(self,messages,tools):
            if failure=='timeout':raise TimeoutError()
            if failure=='network':raise httpx.ConnectError('private-provider-secret')
            if failure=='json':content='not-json-private-model-output'
            elif failure=='fields':content=json.dumps({'lessons':[{'title':'private-field-value'}]})
            else:content=json.dumps({'lessons':[{'title':'方法','when':'条件','strategy':'验证','evidence':[999999]}]})
            yield {'type':'response','message':{'content':content}}
    with TestClient(create_app(settings)) as client:
        session=client.post('/api/sessions').json()['id'];runtime=client.app.state.runtime
        seed(runtime.store,session);runtime.learning.provider=BrokenReflector()
        response=client.post(f'/api/sessions/{session}/experiences/extract',json={'run_id':'r','confirmed':True})
        assert response.status_code==expected_status
        assert expected_text in response.json()['detail']
        assert 'private' not in response.text
        assert runtime.learning.list(session)==[]


def test_preview_dropdown_discovers_nested_pages_and_prioritizes_successful_generated_files(harness):
    settings,*_=harness
    with TestClient(create_app(settings)) as client:
        session=client.post('/api/sessions').json()['id'];runtime=client.app.state.runtime
        root=runtime.uploads.workspace(session);root.mkdir(parents=True,exist_ok=True)
        for entry in ['index.html','dist/index.html','pages/profile.HTM','.git/hidden.html','node_modules/hidden.html','.venv/hidden.html']:
            path=root/entry;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('<h1>Test</h1>',encoding='utf-8')
        runtime.store.event(session,'tool_start',call_id='ok',name='write_file',arguments={'path':'dist/index.html'})
        runtime.store.event(session,'tool_end',call_id='ok',name='write_file',result={'path':'dist/index.html'})
        runtime.store.event(session,'tool_start',call_id='bad',name='write_file',arguments={'path':'index.html'})
        runtime.store.event(session,'tool_end',call_id='bad',name='write_file',result={'error':'denied'})
        result=client.get(f'/api/sessions/{session}/preview/entries')
        assert result.status_code==200
        entries=result.json()['entries'];assert entries[0]['path']=='dist/index.html' and entries[0]['generated']
        assert {entry['path'] for entry in entries}=={'index.html','dist/index.html','pages/profile.HTM'}
        assert not next(entry for entry in entries if entry['path']=='index.html')['generated']
        assert not result.json()['truncated']
        assert client.get('/api/sessions/missing/preview/entries').status_code==404


def test_preview_entries_and_assets_reject_escape_links(harness):
    from ecoder.preview import Preview
    settings,_,tools,runtime,session=harness
    outside=settings.root/'external.html';outside.write_text('<h1>Outside</h1>')
    try:(tools.root/'escape.html').symlink_to(outside)
    except OSError:pytest.skip('symlink privilege unavailable')
    assert Preview(runtime).entries(session)['entries']==[]
    with pytest.raises(ValueError):Preview(runtime).asset(session,'../external.html')
