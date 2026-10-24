"""Inventory and permanently remove files owned by E_coder, never linked projects."""
import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path


class StorageChanged(ValueError):
    pass


class Storage:
    LIMIT = 20000

    def __init__(self, settings, store):
        self.project = settings.root.resolve()
        self.roots = {'uploads':self.project/'.ecoder'/'uploads', 'default':self.project/'default_workspace'}
        self.store = store
        self.secret = secrets.token_bytes(32)

    def path(self, kind, relative):
        if kind not in self.roots:
            raise ValueError('不支持清理此位置')
        root = self.roots[kind]
        if root.resolve() != root or root.is_symlink() or root.is_junction():
            raise ValueError('存储目录已变化，请检查目录位置')
        value = Path(relative)
        if value.is_absolute() or not value.parts or any(part in {'.','..'} or ':' in part for part in value.parts):
            raise ValueError('文件路径无效')
        target = root/value
        for part in [target,*target.parents]:
            if part == root:
                break
            if part.is_symlink() or part.is_junction():
                raise ValueError('不能清理链接指向的内容')
        if not target.resolve().is_relative_to(root):
            raise ValueError('文件路径越界')
        return target

    @staticmethod
    def fingerprint(stat):
        return [stat.st_size,stat.st_mtime_ns,stat.st_ino,stat.st_ctime_ns]

    def token(self, kind, relative, stat):
        raw=json.dumps([kind,relative,self.fingerprint(stat)],ensure_ascii=False,separators=(',',':')).encode()
        signature=hmac.digest(self.secret,raw,hashlib.sha256)
        return base64.urlsafe_b64encode(signature+raw).decode()

    def decode(self, token):
        try:
            raw=base64.b64decode(token,altchars=b'-_',validate=True)
            if not hmac.compare_digest(raw[:32],hmac.digest(self.secret,raw[32:],hashlib.sha256)):
                raise ValueError()
            kind,relative,fingerprint=json.loads(raw[32:])
            target=self.path(kind,relative)
            if not target.is_file() or self.fingerprint(target.stat())!=fingerprint:
                raise StorageChanged('所选文件已变化，请刷新后重新选择')
            return kind,relative,target
        except StorageChanged:
            raise
        except (ValueError,TypeError,OSError,KeyError):
            raise StorageChanged('清理列表已失效，请刷新后重新选择') from None

    def snapshot(self):
        with self.store.connect() as db:
            sessions={row['id']:row['title'] for row in db.execute('SELECT id,title FROM sessions')}
            folders=[dict(row) for row in db.execute('SELECT w.session,w.path,s.title FROM session_workspaces w JOIN sessions s ON s.id=w.session')]
        files=[]
        totals={key:{'bytes':0,'files':0} for key in self.roots}
        skipped=0
        truncated=False
        for kind,root in self.roots.items():
            if not root.exists():
                continue
            if root.resolve()!=root or root.is_symlink() or root.is_junction():
                skipped+=1
                continue
            for parent,dirs,names in os.walk(root,followlinks=False):
                dirs[:]=[name for name in dirs if not (Path(parent)/name).is_symlink() and not (Path(parent)/name).is_junction()]
                for name in names:
                    try:
                        relative=(Path(parent)/name).relative_to(root).as_posix()
                        target=self.path(kind,relative)
                        if not target.is_file():
                            continue
                        stat=target.stat()
                        session=Path(relative).parts[0] if kind=='uploads' else None
                        orphan=kind=='uploads' and session not in sessions
                        files.append({'id':self.token(kind,relative,stat),'kind':kind,'path':relative,'name':name,
                                      'size':stat.st_size,'modified':stat.st_mtime,'session':session,
                                      'session_title':sessions.get(session),'orphan':orphan})
                        totals[kind]['bytes']+=stat.st_size
                        totals[kind]['files']+=1
                        if len(files)>=self.LIMIT:
                            truncated=True
                            break
                    except (OSError,ValueError):
                        skipped+=1
                if truncated:
                    break
            if truncated:
                break
        files.sort(key=lambda item:(not item['orphan'],-item['size'],item['path']))
        return {'files':files,'totals':totals,'bytes':sum(item['bytes'] for item in totals.values()),
                'orphan_bytes':sum(item['size'] for item in files if item['orphan']),
                'orphan_files':sum(1 for item in files if item['orphan']),
                'folders':folders,'locations':{key:str(path) for key,path in self.roots.items()},
                'truncated':truncated,'skipped':skipped}

    def delete(self, tokens):
        if not tokens or len(tokens)>500 or len(set(tokens))!=len(tokens):
            raise ValueError('每次可清理 1–500 个文件，不能重复选择')
        # Validate the entire selection before permanently removing any file.
        targets=[self.decode(token) for token in tokens]
        deleted=[]
        failed=[]
        released=0
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute('SELECT id,path,root FROM uploads').fetchall()
            for token,(kind,relative,target) in zip(tokens,targets):
                try:
                    self.decode(token)  # Recheck immediately before unlinking.
                    size=target.stat().st_size
                    matching=[row['id'] for row in rows if row['root'] and (Path(row['root'])/row['path']).resolve()==target]
                    target.unlink()
                except (OSError,ValueError):
                    failed.append({'path':relative,'reason':'文件正在使用或已变化，请刷新后重试'})
                    continue
                for attachment in matching:
                    db.execute('DELETE FROM uploads WHERE id=?',(attachment,))
                deleted.append({'kind':kind,'path':relative})
                released+=size
                parent=target.parent
                root=self.roots[kind]
                # Only prune empty directories within this managed storage root.
                while parent!=root and parent.is_relative_to(root):
                    if parent.is_symlink() or parent.is_junction() or parent.resolve()!=parent:
                        break
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                    parent=parent.parent
        return {'deleted':len(deleted),'released_bytes':released,'files':deleted,'failed':failed,'recoverable':False}
