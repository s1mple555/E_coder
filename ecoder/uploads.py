"""Use the project default workspace until a session uploads files."""
import base64
import copy
import mimetypes
import os
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

from .store import uid
from .tools import Tools, SKIP

FILE_LIMIT = 20 * 1024 * 1024
BATCH_LIMIT = 100 * 1024 * 1024
SESSION_LIMIT = 250 * 1024 * 1024
IMAGE_LIMIT = 5 * 1024 * 1024
IMAGE_MIMES = {"PNG":"image/png", "JPEG":"image/jpeg", "WEBP":"image/webp", "GIF":"image/gif"}
DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1,10)), *(f"lpt{i}" for i in range(1,10))}


class Uploads:
    def __init__(self, settings, store, skills):
        self.default = (settings.root / "default_workspace").resolve()
        if self.default.parent != settings.root.resolve():
            raise ValueError("默认工作目录必须位于项目内")
        self.default.mkdir(parents=True, exist_ok=True)
        self.base = (settings.root / ".ecoder" / "uploads").resolve()
        self.staging = settings.root / ".ecoder" / "incoming"
        self.base.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.store, self.skills = store, skills

    def upload_workspace(self, session):
        if not re.fullmatch(r"[a-f0-9]{32}", session):
            raise ValueError("会话 ID 无效")
        path = (self.base / session).resolve()
        if path.parent != self.base:
            raise ValueError("文件目录越界")
        return path

    def workspace(self, session):
        path = self.upload_workspace(session)
        local = self.local_folder(session)
        if local:
            target = Path(local)
            if not target.is_dir():
                raise ValueError("所选本地文件夹已不存在，请重新选择")
            return target
        with self.store.connect() as db:
            uploaded = db.execute("SELECT 1 FROM uploads WHERE session=? LIMIT 1", (session,)).fetchone()
        # Generated files may remain after the final uploaded attachment is cleaned.
        return path if uploaded or (path.is_dir() and any(path.iterdir())) else self.default

    def local_folder(self, session):
        with self.store.connect() as db:
            row = db.execute("SELECT path FROM session_workspaces WHERE session=?", (session,)).fetchone()
        return row[0] if row else None

    def bind_folder(self, session, value):
        self.upload_workspace(session)  # Validate session ID before persisting.
        path = Path(value.strip().strip('"'))
        if not path.is_absolute():
            raise ValueError("请提供本机文件夹的绝对路径")
        path = path.resolve(strict=True)
        if not path.is_dir():
            raise ValueError("请选择文件夹，不能选择文件")
        with self.store.connect() as db:
            db.execute("INSERT INTO session_workspaces(session,path) VALUES(?,?) ON CONFLICT(session) DO UPDATE SET path=excluded.path", (session,str(path)))
        return {"path":str(path), "name":path.name or str(path)}

    def tools(self, session):
        paths = []
        for record in self.records(session):
            try:
                paths.append(self.attachment_path(session, record["id"]))
            except ValueError:
                continue
        return Tools(self.workspace(session), self.store, self.skills, attachments=paths)

    def attachment_path(self, session, attachment):
        with self.store.connect() as db:
            row = db.execute("SELECT path,root FROM uploads WHERE session=? AND id=?", (session,attachment)).fetchone()
        if not row:
            raise ValueError("附件不存在于当前会话")
        root = Path(row["root"]).resolve()
        path = (root / self.relative(row["path"])).resolve()
        if not path.is_relative_to(root):
            raise ValueError("附件路径越界")
        return path

    def relative(self, value):
        value = value.replace("\\", "/")
        parts = value.split("/")
        if (not parts or len(value)>500 or any(not p or p in {".",".."} for p in parts)
                or any(p.endswith(("."," ")) or ":" in p or len(p)>120
                       or any(ord(c)<32 or c in '<>"|?*' for c in p)
                       or p.split(".")[0].casefold() in DEVICES
                       or p.casefold() in SKIP or p.casefold()==".env" or p.casefold().startswith(".env.")
                       for p in parts)):
            raise ValueError(f"文件路径不可上传：{value[:120]}")
        return str(PurePosixPath(*parts))

    def records(self, session):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,path,mime,size,created FROM uploads WHERE session=? ORDER BY created,id", (session,))]

    def selected(self, session, ids):
        if len(ids)>30 or len(ids)!=len(set(ids)):
            raise ValueError("每条消息最多选择 30 个附件，且不能重复")
        records = {item["id"]:item for item in self.records(session)}
        if any(item not in records for item in ids):
            raise ValueError("附件不存在于当前会话")
        selected = [records[item] for item in ids]
        images = [item for item in selected if item["mime"] in IMAGE_MIMES.values()]
        if len(images)>4:
            raise ValueError("每条消息最多附带 4 张图片")
        for item in images:
            path = self.attachment_path(session, item["id"])
            if not path.is_file() or path.stat().st_size>IMAGE_LIMIT:
                raise ValueError("图片已不存在或超过 5 MB 视觉输入限制")
        return selected

    async def receive(self, session, files, paths):
        if not files or len(files)>1000 or len(files)!=len(paths):
            raise ValueError("每批上传 1–1000 个文件，文件与相对路径必须对应")
        relative = [self.relative(path) for path in paths]
        if len({path.casefold() for path in relative})!=len(relative):
            raise ValueError("本批次包含重名文件，请调整名称后上传")
        # The first upload must go to its own directory before metadata exists.
        tools = Tools(self.upload_workspace(session), self.store, self.skills)
        existing = {item["path"].casefold() for item in self.records(session)}
        for path in relative:
            if path.casefold() in existing or tools.path(path).exists():
                raise FileExistsError(f"文件已存在，不会覆盖：{path}")
        current = sum(item["size"] for item in self.records(session))
        staged, created, records, total = [], [], [], 0
        try:
            for file, path in zip(files, relative):
                with tempfile.NamedTemporaryFile(dir=self.staging, delete=False) as handle:
                    temp = Path(handle.name)
                    staged.append(temp)
                    size = 0
                    while chunk := await file.read(64*1024):
                        size += len(chunk); total += len(chunk)
                        if size>FILE_LIMIT or total>BATCH_LIMIT or current+total>SESSION_LIMIT:
                            raise ValueError("上传超出限制：单文件 20 MB、单批 100 MB、会话上传总量 250 MB")
                        handle.write(chunk)
                mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if mime.startswith("image/") and mime!="image/svg+xml":
                    try:
                        with Image.open(temp) as image:
                            if image.width*image.height>16_000_000:
                                raise ValueError("图片像素过大，最多 1600 万像素")
                            mime = IMAGE_MIMES.get(image.format, "application/octet-stream")
                            image.verify()
                    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                        raise ValueError(f"图片文件无法解码：{path}")
                # SVG and HTML are always downloaded, never rendered inline.
                records.append({"id":uid(), "path":path, "mime":mime, "size":size, "created":time.time()})
            with self.store.connect() as db:
                for temp, record in zip(staged, records):
                    target = tools.path(record["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as output, temp.open("rb") as source:
                        created.append(target)
                        shutil.copyfileobj(source, output)
                    db.execute("INSERT INTO uploads(id,session,path,mime,size,created,root) VALUES(?,?,?,?,?,?,?)",
                               (record["id"],session,record["path"],record["mime"],record["size"],record["created"],str(tools.root)))
            return records
        except BaseException:
            for target in created:
                target.unlink(missing_ok=True)
            raise
        finally:
            for temp in staged:
                temp.unlink(missing_ok=True)
            for file in files:
                await file.close()

    def scan(self, session, directory=""):
        tools = self.tools(session)
        attachments = self.records(session)
        records = {item["path"]:item for item in attachments
                   if self.attachment_path(session,item["id"]) == (tools.root/item["path"]).resolve()}
        if self.local_folder(session):
            parent = tools.path(self.relative(directory) if directory else ".")
            if not parent.is_dir():
                raise ValueError("目录不存在")
            files = []
            # Only inspect this directory's entries; never traverse the whole project.
            with os.scandir(parent) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        path = tools.path(entry.path)
                        relative = path.relative_to(tools.root).as_posix()
                        is_dir = entry.is_dir(follow_symlinks=False)
                        meta = records.get(relative,{})
                        files.append({"path":relative, "directory":is_dir, "size":0 if is_dir else entry.stat().st_size,
                                      "id":meta.get("id"), "mime":meta.get("mime",mimetypes.guess_type(relative)[0] or "application/octet-stream")})
                        if len(files)>=2000:
                            return {"files":files,"truncated":True,"directory":directory,"local_folder":self.local_folder(session)}
                    except (OSError, ValueError):
                        continue
            files.sort(key=lambda item:(not item["directory"],item["path"].casefold()))
            if not directory:
                for item in attachments:
                    if item["path"] not in records:
                        files.append({**item,"attachment":True})
            return {"files":files,"truncated":False,"directory":directory,"local_folder":self.local_folder(session)}
        files = []
        for parent, dirs, names in os.walk(tools.root):
            dirs[:] = sorted(d for d in dirs if d.casefold() not in SKIP and not (Path(parent)/d).is_symlink())
            for name in sorted(names):
                try:
                    path=tools.path(str(Path(parent)/name))
                    stat=path.stat()
                    relative=path.relative_to(tools.root).as_posix()
                    meta=records.get(relative,{})
                    files.append({"path":relative,"size":stat.st_size,"id":meta.get("id"),"mime":meta.get("mime",mimetypes.guess_type(relative)[0] or "application/octet-stream")})
                    if len(files)>=2000:
                        return {"files":files,"truncated":True}
                except (OSError,ValueError):
                    continue
        return {"files":files,"truncated":False}

    def request_messages(self, session, messages):
        """Inject current-turn images only; never persist base64 in chat history."""
        result=copy.deepcopy(messages)
        last_user=max((i for i,m in enumerate(result) if m["role"]=="user"),default=-1)
        for i,message in enumerate(result):
            ids=message.pop("attachments",[])
            if message["role"]!="user" or not ids:
                continue
            records=self.selected(session,ids) if i==last_user else []
            if records:
                message["content"] += "\n\n[附件读取路径：可通过 read_file 按此绝对路径读取]\n" + "\n".join(
                    f"{item['path']}: {self.attachment_path(session,item['id'])}" for item in records)
            images=[item for item in records if item["mime"] in IMAGE_MIMES.values()]
            if images:
                content=[{"type":"text","text":message["content"]}]
                for item in images:
                    raw=self.attachment_path(session,item["id"]).read_bytes()
                    content.append({"type":"image_url","image_url":{"url":f"data:{item['mime']};base64,"+base64.b64encode(raw).decode("ascii")}})
                message["content"]=content
        return result
