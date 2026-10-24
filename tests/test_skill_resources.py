import asyncio
import json
import sys

import pytest
import yaml

from test_harness import harness
from ecoder.runtime import Run
from fastapi.testclient import TestClient
from app import create_app


def add_skill(settings):
    root=settings.root/'skills'/'resource-check'
    (root/'scripts').mkdir(parents=True)
    (root/'SKILL.md').write_text('---\nname: resource-check\ndescription: test resources\n---\nRead the bundled script.',encoding='utf-8')
    (root/'scripts'/'check.py').write_text('print("skill script ran")',encoding='utf-8')
    (root/'references').mkdir()
    (root/'references'/'notes.md').write_text('resource notes',encoding='utf-8')
    (root/'.env').write_text('SECRET=do-not-expose',encoding='utf-8')
    return root


def test_load_skill_includes_directory_resources_and_real_runtime(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    result=asyncio.run(tools.execute(session,'load_skill',{'name':'resource-check'}))
    assert result['directory']==str(root)
    assert result['runtimes']['python']==sys.executable
    assert 'scripts/check.py' in result['resources'] and 'references/notes.md' in result['resources']
    assert '.env' not in result['resources']
    assert 'do-not-expose' not in json.dumps(result)
    assert 'Read the bundled script.' in result['instructions']
    assert '绝对路径' in result['execution_note']


def test_resource_reads_do_not_allow_writes_or_credentials(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    notes=str(root/'references'/'notes.md')
    result=asyncio.run(tools.execute(session,'read_file',{'path':notes,'offset':1,'limit':20}))
    assert 'resource notes' in result['text']
    for value in (str(root/'.env'),str(settings.root/'outside.txt')):
        with pytest.raises(ValueError):tools.path(value,read_only=True)
    with pytest.raises(ValueError):tools.preview('write_file',{'path':notes,'content':'overwrite skill'})
    assert (root/'references'/'notes.md').read_text()=='resource notes'


def test_runtime_configuration_preserves_argv_without_shell_parsing(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    expected=[sys.executable,str(root/'scripts'/'check.py')]
    (root/'runtime.conf').write_text(yaml.safe_dump({'Runtime':'Python','Argv':expected},allow_unicode=True),encoding='utf-8')
    result=tools.skills.describe('resource-check')
    assert result['configured_runtime']['Argv']==expected


def test_skill_preview_api_reports_execution_context(harness):
    settings,*_=harness
    root=add_skill(settings)
    with TestClient(create_app(settings)) as client:
        response=client.get('/api/skills/resource-check')
        assert response.status_code==200
        data=response.json()
        assert data['directory']==str(root)
        assert data['content']==data['instructions']
        assert 'scripts/check.py' in data['resources']


def test_skill_script_runs_from_absolute_path_after_approval(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    run=Run()
    runtime.active[session]=run
    original=runtime.emit
    def emit(session,run,kind,**data):
        result=original(session,run,kind,**data)
        if kind=='approval_request':runtime.approve(session,data['approval_id'],True)
        return result
    runtime.emit=emit
    try:
        result=asyncio.run(runtime.invoke(session,run,{'id':'skill-call','function':{'name':'run_command','arguments':json.dumps({'argv':[sys.executable,str(root/'scripts'/'check.py')],'timeout':10})}}))
    finally:runtime.active.clear()
    assert result['exit_code']==0 and 'skill script ran' in result['output']
    assert any(event['type']=='approval_request' for event in store.events(session))


def test_skill_resource_symlink_cannot_escape_skill_root(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    outside=settings.root/'secret.txt'
    outside.write_text('outside')
    try:(root/'references'/'outside.md').symlink_to(outside)
    except OSError:pytest.skip('symlinks unavailable')
    assert 'references/outside.md' not in tools.skills.describe('resource-check')['resources']
    with pytest.raises(ValueError):tools.path(str(root/'references'/'outside.md'),read_only=True)
