"""Windows AppContainer launcher. No capabilities, no inherited credentials.

The caller owns the disposable directory and its ACL. Never grant access to a
user workspace: this launcher only sees a staged copy.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess
import time
import uuid


def launch(argv, cwd, box, timeout, cancelled):
    if os.name != 'nt':
        raise RuntimeError('AppContainer 沙箱仅支持 Windows；未执行命令')
    k = C.WinDLL('kernel32', use_last_error=True)
    u = C.WinDLL('userenv', use_last_error=True)
    a = C.WinDLL('advapi32', use_last_error=True)
    P = C.c_void_p
    SIZE = C.c_size_t
    class SI(C.Structure):
        _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                    ('x', W.DWORD), ('y', W.DWORD), ('xs', W.DWORD), ('ys', W.DWORD),
                    ('xc', W.DWORD), ('yc', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                    ('show', W.WORD), ('cb2', W.WORD), ('reserved2', P),
                    ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]
    class SIX(C.Structure):
        _fields_ = [('si', SI), ('attrs', P)]
    class PI(C.Structure):
        _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]
    class CAPS(C.Structure):
        _fields_ = [('sid', P), ('caps', P), ('count', W.DWORD), ('reserved', W.DWORD)]
    class BASIC(C.Structure):
        _fields_ = [('process_time', C.c_int64), ('job_time', C.c_int64), ('flags', W.DWORD),
                    ('min_ws', SIZE), ('max_ws', SIZE), ('active', W.DWORD), ('affinity', SIZE),
                    ('priority', W.DWORD), ('scheduling', W.DWORD)]
    class IO(C.Structure):
        _fields_ = [(n, C.c_uint64) for n in ('ro', 'wo', 'oo', 'rb', 'wb', 'ob')]
    class LIMIT(C.Structure):
        _fields_ = [('basic', BASIC), ('io', IO), ('process_memory', SIZE), ('job_memory', SIZE),
                    ('peak_process', SIZE), ('peak_job', SIZE)]
    signatures = {
        'InitializeProcThreadAttributeList': ([P,W.DWORD,W.DWORD,C.POINTER(SIZE)],W.BOOL),
        'UpdateProcThreadAttribute': ([P,W.DWORD,SIZE,P,SIZE,P,P],W.BOOL),
        'DeleteProcThreadAttributeList': ([P],None),
        'CreateProcessW': ([W.LPCWSTR,W.LPWSTR,P,P,W.BOOL,W.DWORD,P,W.LPCWSTR,P,P],W.BOOL),
        'CreateJobObjectW': ([P,W.LPCWSTR],W.HANDLE),
        'SetInformationJobObject': ([W.HANDLE,C.c_int,P,W.DWORD],W.BOOL),
        'AssignProcessToJobObject': ([W.HANDLE,W.HANDLE],W.BOOL),
        'TerminateJobObject': ([W.HANDLE,W.UINT],W.BOOL),
        'ResumeThread': ([W.HANDLE],W.DWORD),
        'WaitForSingleObject': ([W.HANDLE,W.DWORD],W.DWORD),
        'GetExitCodeProcess': ([W.HANDLE,C.POINTER(W.DWORD)],W.BOOL),
        'TerminateProcess': ([W.HANDLE,W.UINT],W.BOOL),
        'CloseHandle': ([W.HANDLE],W.BOOL),
        'LocalFree': ([P],P),
    }
    for name,(args,result) in signatures.items():
        getattr(k,name).argtypes=args; getattr(k,name).restype=result
    u.CreateAppContainerProfile.argtypes=[W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,P,W.DWORD,C.POINTER(P)]
    u.CreateAppContainerProfile.restype=C.c_long
    u.DeleteAppContainerProfile.argtypes=[W.LPCWSTR]
    a.ConvertSidToStringSidW.argtypes=[P,C.POINTER(W.LPWSTR)]
    a.ConvertSidToStringSidW.restype=W.BOOL
    a.FreeSid.argtypes=[P]; a.FreeSid.restype=P
    def check(ok):
        if not ok:
            raise C.WinError(C.get_last_error())
    name='Ecoder.'+uuid.uuid4().hex
    sid=P(); sidtext=W.LPWSTR(); pi=PI(); job=None; attrs=None
    result=u.CreateAppContainerProfile(name,name,'E_coder disposable command',None,0,C.byref(sid))
    if result < 0:
        raise RuntimeError(f'无法创建 AppContainer (HRESULT {result & 0xffffffff:08x})；未执行命令')
    try:
        check(a.ConvertSidToStringSidW(sid,C.byref(sidtext)))
        # Only the disposable copy receives a low-integrity ACL.
        for options in (['/grant',f'*{sidtext.value}:(OI)(CI)F','/T','/Q'],
                        ['/setintegritylevel','(OI)(CI)L','/T','/Q']):
            completed=subprocess.run(['icacls',str(box),*options],capture_output=True,creationflags=0x08000000)
            if completed.returncode:
                raise RuntimeError('无法设置沙箱目录 ACL；未执行命令')
        size=SIZE()
        k.InitializeProcThreadAttributeList(None,2,0,C.byref(size))
        attrs=C.create_string_buffer(size.value)
        check(k.InitializeProcThreadAttributeList(attrs,2,0,C.byref(size)))
        caps=CAPS(sid,None,0,0)
        check(k.UpdateProcThreadAttribute(attrs,0,0x20009,C.byref(caps),C.sizeof(caps),None,None))
        import msvcrt
        with open(box/'output.log','w+b',buffering=0) as output, open(os.devnull,'rb') as stdin:
            handles=(W.HANDLE*2)(msvcrt.get_osfhandle(stdin.fileno()),msvcrt.get_osfhandle(output.fileno()))
            for handle in handles: os.set_handle_inheritable(handle,True)
            try:
                check(k.UpdateProcThreadAttribute(attrs,0,0x20002,handles,C.sizeof(handles),None,None))
                si=SIX(); si.si.cb=C.sizeof(si); si.attrs=C.cast(attrs,P)
                si.si.flags=0x100; si.si.stdin=handles[0]; si.si.stdout=si.si.stderr=handles[1]
                env={'SystemRoot':os.environ.get('SystemRoot',r'C:\Windows'),
                     'WINDIR':os.environ.get('SystemRoot',r'C:\Windows'),
                     'TEMP':str(box/'temp'),'TMP':str(box/'temp'),
                     'PATH':str(box/'runtime')+os.pathsep+os.environ.get('SystemRoot',r'C:\Windows')+'\\System32',
                     'ECODER_SKILLS_DIR':str(box/'skills'),'PYTHONIOENCODING':'utf-8','PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
                for key in ('USERPROFILE','LOCALAPPDATA','APPDATA','SystemDrive','ComSpec'):
                    if key in os.environ: env[key]=os.environ[key]
                block=C.create_unicode_buffer('\0'.join(f'{key}={value}' for key,value in sorted(env.items()))+'\0\0')
                job=k.CreateJobObjectW(None,None); check(job)
                limit=LIMIT(); limit.basic.flags=0x2000|0x8|0x100|0x200
                limit.basic.active=16; limit.process_memory=512*1024**2; limit.job_memory=1024**3
                check(k.SetInformationJobObject(job,9,C.byref(limit),C.sizeof(limit)))
                command=C.create_unicode_buffer(subprocess.list2cmdline([str(x) for x in argv]))
                check(k.CreateProcessW(str(argv[0]),command,None,None,True,0x80000|0x400|0x4|0x08000000,block,str(cwd),C.byref(si),C.byref(pi)))
                check(k.AssignProcessToJobObject(job,pi.process))
                if k.ResumeThread(pi.thread)==0xffffffff: check(False)
                start=time.monotonic()
                while k.WaitForSingleObject(pi.process,50)==258:
                    if cancelled.is_set(): raise InterruptedError('沙箱命令已取消')
                    if time.monotonic()-start>timeout: raise TimeoutError('沙箱命令超时')
                    if output.tell()>2_000_000: raise RuntimeError('沙箱输出超过 2 MB，命令已终止')
                code=W.DWORD(); check(k.GetExitCodeProcess(pi.process,C.byref(code)))
                # Kill descendants before reading output or synchronizing files.
                check(k.TerminateJobObject(job,1))
                k.WaitForSingleObject(job,5000)
                output.seek(0)
                return {'exit_code':code.value,'output':output.read(24000).decode('utf-8',errors='replace'),
                        'output_limit':24000,'execution_mode':'sandbox','sandbox':'windows-appcontainer'}
            finally:
                for handle in handles: os.set_handle_inheritable(handle,False)
    finally:
        if job:
            k.TerminateJobObject(job,1)
            k.WaitForSingleObject(job,5000)
        if pi.process:
            k.TerminateProcess(pi.process,1)
            k.WaitForSingleObject(pi.process,5000)
        for handle in (pi.thread,pi.process,job):
            if handle: k.CloseHandle(handle)
        if attrs: k.DeleteProcThreadAttributeList(attrs)
        if sidtext: k.LocalFree(sidtext)
        if sid: a.FreeSid(sid)
        u.DeleteAppContainerProfile(name)
