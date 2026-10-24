import asyncio
import json
from pathlib import Path

import pytest

from test_uploads import uploaded_app, send_files


def connect(client, session, path):
    return client.post(f'/api/sessions/{session}/folder',json={'path':str(path)})


def test_folder_is_a_live_reference_not_a_copy(uploaded_app,tmp_path,monkeypatch):
    application,client,session=uploaded_app
    original=tmp_path/'original'
    original.mkdir()
    (original/'src').mkdir()
    code=original/'src'/'代码.py'
    code.write_text('original = 1',encoding='utf-8')
    # Binding must not read file content or recursively traverse the project.
    with monkeypatch.context() as m:
        m.setattr(Path,'read_bytes',lambda *_:pytest.fail('bind read file bytes'))
        m.setattr(Path,'read_text',lambda *a,**k:pytest.fail('bind read file text'))
        m.setattr('os.walk',lambda *_:pytest.fail('bind recursively traversed folder'))
        assert connect(client,session,original).status_code==200
    uploads=application.state.runtime.uploads
    assert uploads.workspace(session)==original
    assert uploads.records(session)==[]
    assert not uploads.upload_workspace(session).exists()
    tools=uploads.tools(session)
    code.write_text('original = 2',encoding='utf-8')
    assert 'original = 2' in asyncio.run(tools.execute(session,'read_file',{'path':'src/代码.py','offset':1,'limit':20}))['text']
    args={'path':'src/代码.py','content':'original = 3'}
    asyncio.run(tools.execute(session,'write_file',args,tools.preview('write_file',args)))
    assert code.read_text(encoding='utf-8')=='original = 3'
    assert str(original) in application.state.runtime.system(session)['content']
    from ecoder.runtime import Run
    call={'id':'read-local','function':{'name':'read_file','arguments':json.dumps({'path':'src/代码.py'})}}
    result=asyncio.run(application.state.runtime.invoke(session,Run(),call))
    assert 'original = 3' in result['text']


def test_folder_listing_is_lazy_and_downloads_stay_inside_root(uploaded_app,tmp_path,monkeypatch):
    application,client,session=uploaded_app
    folder=tmp_path/'project'
    (folder/'nested').mkdir(parents=True)
    (folder/'nested'/'inside.txt').write_text('inside')
    (folder/'.env').write_text('do not show')
    (tmp_path/'outside.txt').write_text('outside')
    assert connect(client,session,folder).status_code==200
    with monkeypatch.context() as m:
        m.setattr('os.walk',lambda *_:pytest.fail('listing recursively walked folder'))
        root=client.get(f'/api/sessions/{session}/files').json()
    assert [item['path'] for item in root['files']]==['nested']
    assert root['files'][0]['directory'] is True
    children=client.get(f'/api/sessions/{session}/files',params={'path':'nested'}).json()
    assert children['files'][0]['path']=='nested/inside.txt'
    assert client.get(f'/api/sessions/{session}/content',params={'path':'nested/inside.txt'}).content==b'inside'
    for path in ('../outside.txt','.env'):
        assert client.get(f'/api/sessions/{session}/content',params={'path':path}).status_code==400
    assert client.get(f'/api/sessions/{session}/files',params={'path':'../'}).status_code==400


def test_folder_reference_persists_and_deletion_keeps_originals(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    root=tmp_path/'project'
    root.mkdir()
    (root/'keep.txt').write_text('keep')
    assert connect(client,session,root).status_code==200
    uploads=application.state.runtime.uploads
    restored=type(uploads)(application.state.runtime.settings,application.state.store,application.state.runtime.skills)
    assert restored.workspace(session)==root
    other=client.post('/api/sessions').json()['id']
    assert restored.workspace(other)==uploads.default
    assert client.get(f'/api/sessions/{session}').json()['local_folder']==str(root)
    assert client.delete(f'/api/sessions/{session}').status_code==200
    with application.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM session_workspaces WHERE session=?',(session,)).fetchone()[0]==0
    assert (root/'keep.txt').read_text()=='keep'


def test_invalid_busy_and_cross_origin_folder_selection(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    for path in ('relative',tmp_path/'missing'):
        assert connect(client,session,path).status_code==400
    file=tmp_path/'file.txt'
    file.write_text('file')
    assert connect(client,session,file).status_code==400
    runtime=application.state.runtime
    for collection in (runtime.active,runtime.uploading):
        if isinstance(collection,dict):collection[session]=object()
        else:collection.add(session)
        try:assert connect(client,session,tmp_path).status_code==409
        finally:collection.clear()
    assert client.post(f'/api/sessions/{session}/folder',json={'path':str(tmp_path)},headers={'Origin':'https://other.example'}).status_code==403
    assert runtime.uploads.local_folder(session) is None


def test_uploads_are_independent_of_selected_folder(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    root=tmp_path/'project'
    root.mkdir()
    (root/'keep.txt').write_text('original')
    assert connect(client,session,root).status_code==200
    assert send_files(client,session,[('keep.txt',b'attachment','text/plain')]).status_code==200
    record=send_files(client,session,[('new.txt',b'uploaded','text/plain')]).json()['files'][0]
    assert not (root/'new.txt').exists()
    assert application.state.runtime.uploads.attachment_path(session,record['id']).read_bytes()==b'uploaded'
    assert application.state.runtime.uploads.selected(session,[record['id']])
    assert connect(client,session,tmp_path).status_code==200
    assert (root/'keep.txt').read_text()=='original'


def test_missing_bound_folder_can_be_reselected_without_recreation(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    root=tmp_path/'empty'
    root.mkdir()
    assert connect(client,session,root).status_code==200
    root.rmdir()
    assert client.get(f'/api/sessions/{session}/files').status_code==400
    assert not root.exists()
    assert connect(client,session,tmp_path).status_code==200


def test_native_picker_result_and_cancel(uploaded_app,monkeypatch,tmp_path):
    import app as app_module
    _,client,_=uploaded_app
    async def chosen():return str(tmp_path)
    monkeypatch.setattr(app_module,'pick_folder',chosen)
    assert client.post('/api/folders/pick').json()['path']==str(tmp_path)
    async def cancelled():return ''
    monkeypatch.setattr(app_module,'pick_folder',cancelled)
    assert client.post('/api/folders/pick').json()['path']==''
    assert client.post('/api/folders/pick',headers={'Origin':'https://other.example'}).status_code==403
