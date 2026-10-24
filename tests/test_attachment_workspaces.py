import asyncio

import pytest

from test_uploads import uploaded_app,send_files,png
from test_local_folders import connect
from ecoder.store import Store,uid


def test_existing_attachments_survive_folder_changes(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    image=png()
    result=send_files(client,session,[('photo.png',image,'image/png'),('same.txt',b'attachment text','text/plain')])
    assert result.status_code==200
    photo,text=result.json()['files']
    uploads=application.state.runtime.uploads
    original=uploads.attachment_path(session,text['id'])
    project=tmp_path/'project'
    project.mkdir()
    (project/'same.txt').write_text('project text')
    assert connect(client,session,project).status_code==200
    assert uploads.workspace(session)==project
    assert uploads.attachment_path(session,text['id'])==original
    assert client.get(f'/api/sessions/{session}/images/{photo["id"]}').content==image
    assert client.get(f'/api/sessions/{session}/content',params={'attachment':text['id']}).content==b'attachment text'
    assert client.get(f'/api/sessions/{session}/content',params={'path':'same.txt'}).content==b'project text'
    tools=uploads.tools(session)
    args={'path':str(original),'offset':1,'limit':20}
    assert 'attachment text' in asyncio.run(tools.execute(session,'read_file',args))['text']
    files=client.get(f'/api/sessions/{session}/files').json()['files']
    assert len([file for file in files if file['path']=='same.txt'])==2
    assert next(file for file in files if file.get('attachment') and file['path']=='same.txt')['id']==text['id']
    assert not (project/'photo.png').exists()
    assert connect(client,session,tmp_path).status_code==200
    request=uploads.request_messages(session,[{'role':'user','content':'read','attachments':[text['id'],photo['id']]}])
    assert str(original) in request[0]['content'][0]['text']
    assert request[0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert original.read_bytes()==b'attachment text'


def test_attachment_access_does_not_grant_parent_or_other_session(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    record=send_files(client,session,[('allowed.txt',b'allowed','text/plain')]).json()['files'][0]
    uploads=application.state.runtime.uploads
    root=tmp_path/'project'
    root.mkdir()
    assert connect(client,session,root).status_code==200
    path=uploads.attachment_path(session,record['id'])
    (path.parent/'not_uploaded.txt').write_text('private')
    tools=uploads.tools(session)
    assert tools.path(str(path))==path
    with pytest.raises(ValueError):tools.path(str(path.parent/'not_uploaded.txt'))
    with pytest.raises(ValueError):tools.path(str(path.parent))
    other=client.post('/api/sessions').json()['id']
    with pytest.raises(ValueError):uploads.tools(other).path(str(path))
    assert client.get(f'/api/sessions/{other}/content',params={'attachment':record['id']}).status_code==400


def test_legacy_upload_locations_are_preserved_on_schema_upgrade(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    store=application.state.store
    uploads=application.state.runtime.uploads
    local=tmp_path/'legacy_project'
    local.mkdir()
    (local/'old.txt').write_text('old local attachment')
    assert connect(client,session,local).status_code==200
    attachment=uid()
    other=client.post('/api/sessions').json()['id']
    upload_root=uploads.upload_workspace(other)
    upload_root.mkdir()
    (upload_root/'old.txt').write_text('old uploaded attachment')
    other_attachment=uid()
    with store.connect() as db:
        db.execute('ALTER TABLE uploads DROP COLUMN root')
        for sid,aid in ((session,attachment),(other,other_attachment)):
            db.execute('INSERT INTO uploads(id,session,path,mime,size,created) VALUES(?,?,?,?,?,?)',(aid,sid,'old.txt','text/plain',20,1))
    Store(store.path)
    assert uploads.attachment_path(session,attachment)==local/'old.txt'
    assert uploads.attachment_path(other,other_attachment)==upload_root/'old.txt'
    assert connect(client,session,tmp_path).status_code==200
    assert uploads.attachment_path(session,attachment).read_text()=='old local attachment'
    assert send_files(client,session,[('old.txt',b'new','text/plain')]).status_code==409
