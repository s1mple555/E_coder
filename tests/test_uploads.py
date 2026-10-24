import asyncio
import io
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import create_app
from ecoder.config import ROOT, Settings


@pytest.fixture
def uploaded_app(tmp_path):
    shutil.copytree(ROOT/'skills',tmp_path/'skills')
    shutil.copytree(ROOT/'static',tmp_path/'static')
    settings=Settings(root=tmp_path,workspace=tmp_path/'legacy')
    application=create_app(settings)
    with TestClient(application) as client:
        session=client.post('/api/sessions').json()['id']
        yield application,client,session


def send_files(client,session,items):
    parts=[]
    for path,body,mime in items:
        parts.append(('files',(path.split('/')[-1],body,mime)))
        parts.append(('paths',(None,path)))
    return client.post(f'/api/sessions/{session}/uploads',files=parts)


def png():
    output=io.BytesIO()
    Image.new('RGB',(16,12),'#6571dd').save(output,format='PNG')
    return output.getvalue()


def test_directory_upload_is_the_tool_workspace(uploaded_app):
    application,client,session=uploaded_app
    result=send_files(client,session,[('项目/src/main.py',b'print("uploaded")\n','text/plain'),('项目/说明.txt','中文内容'.encode(),'text/plain')])
    assert result.status_code==200
    assert len(result.json()['files'])==2
    runtime=application.state.runtime
    tools=runtime.uploads.tools(session)
    content=asyncio.run(tools.execute(session,'read_file',{'path':'项目/说明.txt','offset':1,'limit':20}))
    assert '中文内容' in content['text']
    assert '当前会话文件目录' in runtime.system(session)['content']
    files=client.get(f'/api/sessions/{session}/files').json()['files']
    assert {item['path'] for item in files}=={'项目/src/main.py','项目/说明.txt'}
    assert client.get(f'/api/sessions/{session}/content',params={'path':'项目/说明.txt'}).content=='中文内容'.encode()
    assert 'workspace' not in client.get('/api/status').json()
    assert send_files(client,session,[('项目/说明.txt',b'overwrite','text/plain')]).status_code==409
    assert tools.path('项目/说明.txt').read_text(encoding='utf-8')=='中文内容'


@pytest.mark.parametrize('path',['../escape.txt','C:/escape.txt','/absolute.txt','folder/../escape','folder/.env','folder/.git/config','NUL.txt','nested/file.txt:stream','folder/trailing.'])
def test_upload_rejects_paths_without_partial_writes(uploaded_app,path):
    application,client,session=uploaded_app
    response=send_files(client,session,[('valid.txt',b'first','text/plain'),(path,b'bad','text/plain')])
    assert response.status_code==400
    assert client.get(f'/api/sessions/{session}/files').json()['files']==[]
    assert application.state.runtime.uploads.records(session)==[]


def test_images_are_added_to_model_request_and_not_saved_as_base64(uploaded_app):
    application,client,session=uploaded_app
    image=send_files(client,session,[('截图.png',png(),'image/png')]).json()['files'][0]
    assert client.get(f'/api/sessions/{session}/images/{image["id"]}').headers['content-type']=='image/png'
    seen=[]
    class Capture:
        async def stream(self,messages,tools):
            seen.extend(messages)
            yield {'type':'response','message':{'role':'assistant','content':'received'}}
    runtime=application.state.runtime
    runtime.provider=Capture()
    assert client.post(f'/api/sessions/{session}/runs',json={'attachments':[image['id']]}).status_code==200
    # Event stream terminates once the background runtime has completed.
    assert client.get(f'/api/sessions/{session}/stream').status_code==200
    content=next(message['content'] for message in seen if message['role']=='user')
    assert content[1]['type']=='image_url'
    assert content[1]['image_url']['url'].startswith('data:image/png;base64,')
    history=application.state.store.messages(session)
    assert history[0]['attachments']==[image['id']]
    assert 'base64' not in str(history)
    assert all('attachments' not in message for message in seen)


def test_attachments_and_file_roots_are_session_scoped(uploaded_app):
    application,client,session=uploaded_app
    record=send_files(client,session,[('only.txt',b'private','text/plain')]).json()['files'][0]
    other=client.post('/api/sessions').json()['id']
    assert client.get(f'/api/sessions/{other}/files').json()['files']==[]
    assert client.get(f'/api/sessions/{other}/content',params={'path':'only.txt'}).status_code==404
    assert client.post(f'/api/sessions/{other}/runs',json={'message':'read','attachments':[record['id']]}).status_code==409
    assert application.state.runtime.uploads.workspace(other)!=application.state.runtime.uploads.workspace(session)
    assert client.get(f'/api/sessions/{session}/content',params={'path':'../outside'}).status_code==400


def test_upload_busy_limits_origin_and_rollback(uploaded_app,monkeypatch):
    import ecoder.uploads as upload_module
    application,client,session=uploaded_app
    runtime=application.state.runtime
    runtime.uploading.add(session)
    try:
        assert send_files(client,session,[('a.txt',b'hi','text/plain')]).status_code==409
        assert client.delete(f'/api/sessions/{session}').status_code==409
        assert client.post(f'/api/sessions/{session}/runs',json={'message':'wait'}).status_code==409
    finally:
        runtime.uploading.clear()
    monkeypatch.setattr(upload_module,'FILE_LIMIT',5)
    assert send_files(client,session,[('a.txt',b'0123456','text/plain')]).status_code==400
    assert runtime.uploads.records(session)==[]
    assert client.get(f'/api/sessions/{session}/files').json()['files']==[]
    assert not list(runtime.uploads.staging.iterdir())
    assert client.post(f'/api/sessions/{session}/uploads',headers={'Origin':'https://other.example'},files={'files':('x.txt',b'x')}).status_code==403


def test_bad_images_and_duplicate_batch_names(uploaded_app):
    _,client,session=uploaded_app
    assert send_files(client,session,[('broken.png',b'not an image','image/png')]).status_code==400
    assert send_files(client,session,[('a.txt',b'a','text/plain'),('A.txt',b'b','text/plain')]).status_code==400
    assert client.get(f'/api/sessions/{session}/files').json()['files']==[]


def test_generated_files_are_downloadable(uploaded_app):
    application,client,session=uploaded_app
    tools=application.state.runtime.uploads.tools(session)
    args={'path':'result.py','content':'value = 42\n'}
    prepared=tools.preview('write_file',args)
    asyncio.run(tools.execute(session,'write_file',args,prepared))
    files=client.get(f'/api/sessions/{session}/files').json()['files']
    assert files[0]['path']=='result.py'
    assert client.get(f'/api/sessions/{session}/content',params={'path':'result.py'}).content==tools.path('result.py').read_bytes()


def test_default_workspace_is_created_and_shared_until_upload(uploaded_app):
    application,client,session=uploaded_app
    runtime=application.state.runtime
    uploads=runtime.uploads
    default=runtime.settings.root/'default_workspace'
    assert default.is_dir()
    assert uploads.workspace(session)==default
    other=client.post('/api/sessions').json()['id']
    assert uploads.workspace(other)==default
    tools=uploads.tools(session)
    args={'path':'shared.txt','content':'default output'}
    asyncio.run(tools.execute(session,'write_file',args,tools.preview('write_file',args)))
    assert client.get(f'/api/sessions/{other}/content',params={'path':'shared.txt'}).content==b'default output'

    # An identically named upload belongs to the session, without overwriting defaults.
    response=send_files(client,session,[('shared.txt',b'uploaded content','text/plain')])
    assert response.status_code==200
    assert uploads.workspace(session)==uploads.upload_workspace(session)
    assert uploads.workspace(other)==default
    assert (default/'shared.txt').read_text()=='default output'
    assert client.get(f'/api/sessions/{session}/content',params={'path':'shared.txt'}).content==b'uploaded content'

    # Workspace selection survives re-instantiation with the same database.
    restored=type(uploads)(runtime.settings,application.state.store,runtime.skills)
    assert restored.workspace(session)==uploads.upload_workspace(session)
    assert restored.workspace(other)==default


def test_failed_first_upload_keeps_default_workspace(uploaded_app):
    application,client,session=uploaded_app
    uploads=application.state.runtime.uploads
    (uploads.default/'keep.txt').write_text('keep',encoding='utf-8')
    response=send_files(client,session,[('good.txt',b'good','text/plain'),('bad.png',b'broken','image/png')])
    assert response.status_code==400
    assert uploads.workspace(session)==uploads.default
    assert uploads.records(session)==[]
    assert client.get(f'/api/sessions/{session}/files').json()['files'][0]['path']=='keep.txt'
    assert not (uploads.upload_workspace(session)/'good.txt').exists()
