from pathlib import Path

import pytest

from test_uploads import uploaded_app,send_files
from test_local_folders import connect


def inventory(client):
    response=client.get('/api/storage')
    assert response.status_code==200
    return response.json()


def test_inventory_reports_live_default_and_deleted_session_files(uploaded_app):
    application,client,session=uploaded_app
    uploads=application.state.runtime.uploads
    send_files(client,session,[('live.txt',b'123','text/plain')])
    orphan=client.post('/api/sessions').json()['id']
    send_files(client,orphan,[('orphan.txt',b'12345','text/plain')])
    assert client.delete(f'/api/sessions/{orphan}').status_code==200
    (uploads.default/'generated.txt').write_bytes(b'1234567')
    data=inventory(client)
    assert data['bytes']==15
    assert data['totals']=={'uploads':{'bytes':8,'files':2},'default':{'bytes':7,'files':1}}
    assert data['orphan_files']==1 and data['orphan_bytes']==5
    assert data['files'][0]['name']=='orphan.txt'
    assert len(data['locations'])==2


def test_cleanup_removes_bytes_and_upload_index_but_keeps_chat(uploaded_app):
    application,client,session=uploaded_app
    store=application.state.store
    record=send_files(client,session,[('remove.txt',b'remove','text/plain')]).json()['files'][0]
    path=application.state.runtime.uploads.attachment_path(session,record['id'])
    store.append(session,{'role':'user','content':'keep chat','attachments':[record['id']]})
    file=inventory(client)['files'][0]
    result=client.post('/api/storage/delete',json={'files':[file['id']]}).json()
    assert result['deleted']==1 and result['released_bytes']==6 and result['recoverable'] is False
    assert not path.exists()
    assert store.exists(session) and len(store.messages(session))==1
    assert application.state.runtime.uploads.records(session)==[]
    assert client.get(f'/api/sessions/{session}').json()['attachments']==[]
    assert client.get(f'/api/sessions/{session}/content',params={'attachment':record['id']}).status_code==400
    assert inventory(client)['bytes']==0


def test_cleaning_last_upload_does_not_hide_remaining_generated_files(uploaded_app):
    application,client,session=uploaded_app
    uploads=application.state.runtime.uploads
    send_files(client,session,[('remove.txt',b'remove','text/plain')])
    root=uploads.workspace(session)
    (root/'generated.py').write_bytes(b'value=42')
    file=next(file for file in inventory(client)['files'] if file['name']=='remove.txt')
    assert client.post('/api/storage/delete',json={'files':[file['id']]}).status_code==200
    assert uploads.workspace(session)==root
    assert client.get(f'/api/sessions/{session}/content',params={'path':'generated.py'}).content==b'value=42'


def test_local_projects_are_visible_as_references_but_never_cleanup_targets(uploaded_app,tmp_path):
    application,client,session=uploaded_app
    project=tmp_path/'original-project'
    project.mkdir()
    original=project/'important.txt'
    original.write_text('original file')
    assert connect(client,session,project).status_code==200
    storage=application.state.storage
    data=inventory(client)
    assert data['bytes']==0 and data['files']==[]
    assert data['folders'][0]['path']==str(project)
    for relative in ('../../original-project/important.txt',str(original)):
        token=storage.token('default',relative,original.stat())
        assert client.post('/api/storage/delete',json={'files':[token]}).status_code==409
    token=storage.token('external',str(original),original.stat())
    assert client.post('/api/storage/delete',json={'files':[token]}).status_code==409
    assert original.read_text()=='original file'


def test_stale_selection_is_rejected_before_any_file_is_deleted(uploaded_app):
    application,client,_=uploaded_app
    root=application.state.runtime.uploads.default
    (root/'keep.txt').write_bytes(b'keep')
    changing=root/'changing.txt'
    changing.write_bytes(b'old')
    tokens=[file['id'] for file in inventory(client)['files']]
    changing.write_bytes(b'new content')
    response=client.post('/api/storage/delete',json={'files':tokens})
    assert response.status_code==409
    assert (root/'keep.txt').read_bytes()==b'keep'
    assert changing.read_bytes()==b'new content'
    assert client.post('/api/storage/delete',json={'files':['forged']}).status_code==409


def test_busy_cross_origin_and_duplicate_cleanup_are_blocked(uploaded_app):
    application,client,session=uploaded_app
    send_files(client,session,[('keep.txt',b'keep','text/plain')])
    token=inventory(client)['files'][0]['id']
    runtime=application.state.runtime
    for collection in (runtime.active,runtime.uploading):
        if isinstance(collection,dict):collection[session]=object()
        else:collection.add(session)
        try:assert client.post('/api/storage/delete',json={'files':[token]}).status_code==409
        finally:collection.clear()
    assert client.post('/api/storage/delete',json={'files':[token]},headers={'Origin':'https://other.example'}).status_code==403
    assert client.post('/api/storage/delete',json={'files':[token,token]}).status_code==400
    assert inventory(client)['bytes']==4


def test_partial_cleanup_reports_locked_files_and_preserves_their_index(uploaded_app,monkeypatch):
    application,client,session=uploaded_app
    send_files(client,session,[('locked.txt',b'locked','text/plain'),('delete.txt',b'delete','text/plain')])
    original=Path.unlink
    def unlink(path,*args,**kwargs):
        if path.name=='locked.txt':raise PermissionError('locked')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',unlink)
    tokens=[file['id'] for file in inventory(client)['files']]
    result=client.post('/api/storage/delete',json={'files':tokens}).json()
    assert result['deleted']==1 and result['released_bytes']==6 and len(result['failed'])==1
    assert application.state.runtime.uploads.records(session)[0]['path']=='locked.txt'
    assert inventory(client)['bytes']==6


def test_symlink_targets_are_excluded_and_cannot_be_deleted(uploaded_app,tmp_path):
    application,client,_=uploaded_app
    root=application.state.runtime.uploads.default
    outside=tmp_path/'outside.txt'
    outside.write_text('outside')
    link=root/'link.txt'
    try:link.symlink_to(outside)
    except OSError:pytest.skip('symlinks unavailable')
    assert inventory(client)['files']==[]
    token=application.state.storage.token('default','link.txt',outside.stat())
    assert client.post('/api/storage/delete',json={'files':[token]}).status_code==409
    assert outside.read_text()=='outside'
