"""Disposable command workspace with AppContainer containment on Windows.

Only a successful run synchronizes validated regular-file differences. Runtime
and skill copies are disposable. No host ACLs or environment secrets are shared.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading

from .winbox import launch

MAX_BYTES = 128 * 1024 * 1024
MAX_FILES = 6000
BLOCKED = {'.git', '.venv', 'node_modules', '__pycache__', '.ecoder', '.tools'}


def forbidden(parts):
    return any(p.casefold() in BLOCKED or p.casefold() == '.env' or p.casefold().startswith('.env.') for p in parts)


def regular(path):
    info = path.lstat()
    if getattr(info, 'st_file_attributes', 0) & 0x400 or stat.S_ISLNK(info.st_mode):
        raise ValueError('沙箱拒绝符号链接或 Windows 重解析点')
    return info


def files(root):
    result = {}; size = 0
    regular(root)
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not forbidden((d,))]
        for d in dirs: regular(Path(parent) / d)
        for name in names:
            if forbidden((name,)): continue
            path = Path(parent) / name
            info = regular(path)
            if not stat.S_ISREG(info.st_mode): raise ValueError('沙箱只支持普通文件')
            size += info.st_size
            if size > MAX_BYTES or len(result) >= MAX_FILES:
                raise ValueError('沙箱工作区超过 128 MB 或 6000 个文件，请缩小工作区')
            result[path.relative_to(root)] = hashlib.sha256(path.read_bytes()).digest()
    return result


def copy_visible(source, destination):
    snapshot = files(source)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in snapshot:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    return snapshot


def synchronize(source, destination, before, resolve):
    after = files(source)
    changed = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
    # Validate the entire change set before writing any file. A concurrent user
    # edit must never be overwritten by an older staged copy.
    for relative in changed:
        target = resolve(str(relative))
        cursor = destination
        for part in relative.parts:
            cursor = cursor / part
            if cursor.exists() or cursor.is_symlink(): regular(cursor)
        current = hashlib.sha256(target.read_bytes()).digest() if target.exists() else None
        if current != before.get(relative):
            raise ValueError(f'沙箱执行期间文件已改变，未同步：{relative}')
    for relative in changed:
        target = resolve(str(relative))
        if relative not in after:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Replace links/old file identities instead of following hardlinks.
            fd, temporary = tempfile.mkstemp(prefix='.ecoder-sync-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as handle: handle.write((source / relative).read_bytes())
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return [str(p) for p in sorted(changed)]


def run(tools, args, cancelled):
    if os.name != 'nt':
        raise RuntimeError('本机不支持 Windows AppContainer；未执行命令。主机执行需单独审批')
    with tempfile.TemporaryDirectory(prefix='ecoder-box-') as temporary:
        box = Path(temporary)
        stage = box / 'workspace'
        before = copy_visible(tools.root, stage)
        (box / 'temp').mkdir()
        executable = shutil.which(args['argv'][0])
        if executable is None: raise ValueError('找不到命令可执行文件')
        executable = Path(executable).resolve()
        argv = list(args['argv'])
        if executable.name.casefold() in {'python.exe', 'python3.exe', 'pythonw.exe'}:
            # Never use the venv launcher: it points back at the host runtime.
            shutil.copytree(sys.base_prefix, box / 'runtime',
                            ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','tcl','include','libs','Scripts'))
            packages = Path(sys.prefix) / 'Lib' / 'site-packages'
            if packages.exists():
                copy_visible(packages, box / 'runtime' / 'Lib' / 'site-packages')
            argv[0] = str(box / 'runtime' / 'python.exe')
        elif executable.is_relative_to(Path(os.environ.get('SystemRoot', r'C:\Windows')).resolve()):
            argv[0] = str(executable)
        else:
            (box / 'runtime').mkdir()
            shutil.copyfile(executable, box / 'runtime' / executable.name)
            for dll in executable.parent.glob('*.dll'):
                regular(dll); shutil.copyfile(dll, box / 'runtime' / dll.name)
            argv[0] = str(box / 'runtime' / executable.name)
        mappings = [(str(tools.root), str(stage))]
        if tools.skills.root.exists():
            copy_visible(tools.skills.root, box / 'skills')
            mappings.append((str(tools.skills.root.resolve()), str(box / 'skills')))
        for index, attachment in enumerate(tools.attachments):
            source = Path(attachment)
            regular(source)
            target = box / 'inputs' / str(index) / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            mappings.append((str(source), str(target)))
        # Rewrite absolute path arguments only; embedded scripts remain literal.
        for i in range(1, len(argv)):
            for old, new in sorted(mappings, key=lambda row: -len(row[0])):
                value = argv[i].replace('/', '\\')
                if value.casefold() == old.casefold() or value.casefold().startswith(old.casefold() + '\\'):
                    argv[i] = new + value[len(old):]
                    break
        if cancelled.is_set(): raise InterruptedError('沙箱命令已取消')
        result = launch(argv, stage, box, args['timeout'], cancelled)
        if cancelled.is_set(): raise InterruptedError('沙箱命令已取消')
        # Nonzero exit, cancellation and timeouts discard partial modifications.
        result['changed_files'] = synchronize(stage, tools.root, before, tools.path) if result['exit_code'] == 0 else []
        return result


async def command(tools, args):
    cancelled = threading.Event()
    worker = asyncio.create_task(asyncio.to_thread(run, tools, args, cancelled))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        try: await asyncio.shield(worker)
        except Exception: pass
        raise
