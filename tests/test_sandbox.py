import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import time

import pytest
from ecoder.sandbox import copy_visible, synchronize, files
from ecoder.tools import ExecArgs
from test_harness import harness


def test_default_and_host_modes(harness):
    _,_,tools,_,_=harness
    assert ExecArgs(argv=['python']).execution_mode == 'sandbox'
    assert '禁止联网' in tools.preview('run_command', {'argv':['python']})['warning']
    assert '主机执行' in tools.preview('run_command', {'argv':['python'],'execution_mode':'host'})['warning']
    with pytest.raises(ValueError): ExecArgs(argv=['python'], execution_mode='auto')


def test_snapshot_excludes_secrets_and_sync_detects_conflict(tmp_path):
    root=tmp_path/'root';root.mkdir()
    (root/'.env').write_text('secret')
    (root/'.git').mkdir();(root/'.git'/'config').write_text('private')
    (root/'main.txt').write_text('before')
    stage=tmp_path/'stage';before=copy_visible(root,stage)
    assert set(before)=={Path('main.txt')}
    (stage/'main.txt').write_text('after');(stage/'added.txt').write_text('new')
    (root/'main.txt').write_text('user edit')
    with pytest.raises(ValueError,match='文件已改变'):
        synchronize(stage,root,before,lambda s:root/s)
    assert not (root/'added.txt').exists()
    assert (root/'main.txt').read_text()=='user edit'


@pytest.mark.skipif(os.name!='nt',reason='native Windows containment')
def test_real_appcontainer_files_network_children_and_env(harness,tmp_path):
    settings,_,tools,_,_=harness
    outside=tmp_path/'private.txt';outside.write_text('private')
    (tools.root/'existing.txt').write_text('old')
    script='''import pathlib, socket, subprocess, os, json
blocked=[]
for label, fn in [('read', lambda:pathlib.Path(OUTSIDE).read_text()),('write',lambda:pathlib.Path(OUTSIDE).write_text('bad')),('network',lambda:socket.create_connection(('127.0.0.1',PORT),timeout=2)),('internet',lambda:socket.create_connection(('1.1.1.1',443),timeout=2))]:
 try: fn()
 except (PermissionError, TimeoutError): blocked.append(label)
pathlib.Path('existing.txt').unlink()
pathlib.Path('sub').mkdir()
pathlib.Path('sub/result.txt').write_text('中文 output')
child=subprocess.run([os.sys.executable,'-c',"import pathlib; pathlib.Path('child.txt').write_text('child')"],capture_output=True)
print(json.dumps({'blocked':blocked,'child':child.returncode,'secret':os.getenv('SANDBOX_TEST_API_KEY')}))
'''.replace('OUTSIDE',repr(str(outside))).replace('PORT','__PORT__')
    # Prove networking fails even when the destination is actually listening.
    with socket.socket() as server:
        server.bind(('127.0.0.1',0));server.listen()
        script=script.replace('__PORT__',str(server.getsockname()[1]))
        os.environ['SANDBOX_TEST_API_KEY']='never-inherit'
        try:result=asyncio.run(tools.command({'argv':[sys.executable,'-c',script],'timeout':10}))
        finally:os.environ.pop('SANDBOX_TEST_API_KEY',None)
    assert result['exit_code']==0,result
    data=json.loads(result['output'])
    assert data=={'blocked':['read','write','network','internet'],'child':0,'secret':None}
    assert outside.read_text()=='private'
    assert (tools.root/'sub/result.txt').read_text(encoding='utf-8')=='中文 output'
    assert (tools.root/'child.txt').read_text()=='child'
    assert not (tools.root/'existing.txt').exists()
    assert result['sandbox']=='windows-appcontainer'


@pytest.mark.skipif(os.name!='nt',reason='native Windows containment')
def test_failed_command_discards_writes(harness):
    _,_,tools,_,_=harness
    result=asyncio.run(tools.command({'argv':[sys.executable,'-c',"from pathlib import Path;Path('partial').write_text('bad');raise SystemExit(7)"],'timeout':5}))
    assert result['exit_code']==7
    assert not (tools.root/'partial').exists()


@pytest.mark.skipif(os.name!='nt',reason='native Windows containment')
def test_timeout_kills_child_process_tree(harness):
    _,_,tools,_,_=harness
    script="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
    # Capture the launcher's outcome but do not synchronize on a timeout.
    with pytest.raises(TimeoutError):
        asyncio.run(tools.command({'argv':[sys.executable,'-c',script],'timeout':1}))
    assert list(tools.root.iterdir())==[]


def test_link_not_synchronized(tmp_path):
    stage=tmp_path/'stage';stage.mkdir();target=tmp_path/'private';target.write_text('private')
    try:(stage/'escape').symlink_to(target)
    except OSError:pytest.skip('symlink unavailable')
    with pytest.raises(ValueError,match='重解析点'):files(stage)


def is_alive(pid):
    import ctypes as C
    k=C.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[C.c_uint32,C.c_int,C.c_uint32];k.OpenProcess.restype=C.c_void_p
    k.WaitForSingleObject.argtypes=[C.c_void_p,C.c_uint32]
    k.CloseHandle.argtypes=[C.c_void_p]
    handle=k.OpenProcess(0x100000,False,pid)
    if not handle:return False
    try:return k.WaitForSingleObject(handle,0)==258
    finally:k.CloseHandle(handle)


@pytest.mark.skipif(os.name!='nt',reason='native Windows containment')
@pytest.mark.parametrize('cancel',[False,True])
def test_job_cleanup_really_kills_descendants(harness,monkeypatch,cancel):
    from ecoder import sandbox
    _,_,tools,_,_=harness
    original=sandbox.launch; observed={}
    def capture(argv,cwd,box,timeout,signal):
        observed['box']=box
        try:return original(argv,cwd,box,timeout,signal)
        finally:
            log=box/'output.log'
            if log.exists() and log.read_text().strip(): observed['pid']=int(log.read_text().strip())
    monkeypatch.setattr(sandbox,'launch',capture)
    script="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
    async def scenario():
        task=asyncio.create_task(tools.command({'argv':[sys.executable,'-c',script],'timeout':5 if cancel else 1}))
        if cancel:
            for _ in range(300):
                log=observed.get('box',Path('missing'))/'output.log'
                if log.exists() and log.stat().st_size:break
                if task.done():await task
                await asyncio.sleep(.05)
            else:raise AssertionError('sandbox child did not start')
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        else:
            with pytest.raises(TimeoutError):await task
    asyncio.run(scenario())
    assert 'pid' in observed
    assert not is_alive(observed['pid'])
    assert not observed['box'].exists()


def test_sandbox_failure_never_falls_back_to_host(harness,monkeypatch):
    from ecoder import sandbox
    _,_,tools,_,_=harness
    async def unavailable(*args):raise RuntimeError('AppContainer unavailable')
    async def forbidden(*args):raise AssertionError('host fallback must never happen')
    monkeypatch.setattr(sandbox,'command',unavailable)
    monkeypatch.setattr(tools,'host_command',forbidden)
    with pytest.raises(RuntimeError,match='AppContainer unavailable'):
        asyncio.run(tools.command({'argv':['python'],'timeout':1}))
