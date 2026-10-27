import os
import asyncio
import json
from typing import Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr, ConfigDict, field_validator, model_validator

from ecoder.config import Settings, save_model_settings
from ecoder.runtime import Runtime
from ecoder.skills import Skills
from ecoder.store import Store
from ecoder.tools import Tools, CronSchedule
from ecoder.uploads import Uploads, IMAGE_MIMES
from ecoder.folder_picker import pick_folder
from ecoder.storage import Storage, StorageChanged


def create_app(settings=None):
    settings = settings or Settings.load()
    store = Store(settings.root / ".ecoder" / "state.db")
    skills = Skills(settings.root / "skills")
    uploads = Uploads(settings, store, skills)
    tools = Tools(uploads.base, store, skills)
    runtime = Runtime(settings, store, tools, skills, uploads)
    picker_lock = asyncio.Lock()
    storage = Storage(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        store.archive_legacy_runs()
        # An interrupted server run has no surviving approval or executing worker.
        for session in store.sessions():
            events = store.events(session["id"])
            last_start = max((index for index, event in enumerate(events) if event['type'] == 'run_start'), default=-1)
            if last_start >= 0 and not any(event['type'] == 'run_end' for event in events[last_start+1:]):
                history = store.messages(session["id"])
                paired = {m.get("tool_call_id") for m in history if m["role"] == "tool"}
                for msg in history:
                    for call in msg.get("tool_calls", []):
                        if call["id"] not in paired:
                            store.append(session["id"], {"role": "tool", "tool_call_id": call["id"], "content": '{"error":"服务重启，工具结果未知，请检查文件"}'})
                store.event(session["id"], "run_end", status="interrupted", elapsed_ms=0)
        runtime.goals.recover()
        runtime.learning.recover()
        runtime.scheduler.start()
        try:
            yield
        finally:
            await runtime.scheduler.stop()
            await runtime.learning.stop()
            for session_id in list(runtime.active):
                await runtime.stop(session_id, shutdown=True)

    app = FastAPI(title="E_coder", lifespan=lifespan)
    app.state.runtime, app.state.store = runtime, store
    app.state.storage = storage

    @app.get("/api/storage")
    async def storage_snapshot():
        return await asyncio.to_thread(storage.snapshot)

    @app.post("/api/storage/delete")
    async def storage_delete(body: StorageDelete):
        if runtime.active or runtime.uploading:
            raise HTTPException(409, "有任务运行或文件上传中，请结束后再清理存储")
        try:
            return storage.delete(body.files)
        except StorageChanged as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(400, str(error))
        except OSError:
            raise HTTPException(500, "清理失败，请检查文件占用或目录权限")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path == "/api/config":
            # FastAPI's default validation response includes rejected input.
            # Never include credential input in a response, even on failure.
            return JSONResponse({"detail": "配置格式有误：请检查接口地址、模型名称和密钥（密钥不能包含空白或控制字符）。"}, status_code=422, headers={"Cache-Control": "no-store"})
        from fastapi.exception_handlers import request_validation_exception_handler
        return await request_validation_exception_handler(request, error)

    @app.get("/api/config")
    async def get_config():
        return JSONResponse({"base_url": settings.base_url, "model": settings.model,
                             "configured": bool(settings.api_key)}, headers={"Cache-Control": "no-store"})

    @app.post("/api/config")
    async def update_config(body: ModelConfig):
        nonlocal settings
        if runtime.active:
            raise HTTPException(409, "有任务正在运行，请等待结束或停止任务后再保存模型配置。")
        try:
            updated = save_model_settings(settings, base_url=body.base_url, model=body.model,
                                         api_key=body.api_key.get_secret_value() if body.api_key else None)
        except OSError:
            raise HTTPException(500, "无法保存本机配置，请检查项目目录的写入权限。")
        settings = updated
        runtime.settings = updated
        runtime.provider.settings = updated
        runtime.goal_provider.settings = updated
        runtime.learning.provider.settings = updated
        return JSONResponse({"saved": True, "configured": bool(settings.api_key),
                             "base_url": settings.base_url, "model": settings.model},
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/permissions")
    async def update_permissions(body: PermissionConfig):
        nonlocal settings
        if runtime.active:
            raise HTTPException(409, "有任务正在运行，请结束或停止所有任务后再切换权限。")
        try:
            updated = save_model_settings(settings, base_url=settings.base_url, model=settings.model,
                                          permission_mode=body.permission_mode)
        except OSError:
            raise HTTPException(500, "无法保存权限配置，请检查项目目录写入权限。")
        settings = updated
        runtime.settings = updated
        runtime.provider.settings = updated
        runtime.goal_provider.settings = updated
        runtime.learning.provider.settings = updated
        return {"saved": True, "permission_mode": settings.permission_mode}

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        # Local personal service. Reject cross-origin writes / DNS rebinding.
        from urllib.parse import urlparse
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            if urlparse(origin).netloc != request.headers.get("host"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "拒绝跨来源请求"}, status_code=403)
        return await call_next(request)

    def require(session):
        if not store.exists(session):
            raise HTTPException(404, "会话不存在")

    from ecoder.feature_routes import routes, Toggle
    app.include_router(routes(runtime, require))

    @app.get('/api/experiences')
    def all_experiences():
        return {'experiences':runtime.learning.list_all(),'jobs':[]}

    @app.patch('/api/experiences/{identifier}')
    def update_any_experience(identifier:str,body:Toggle):
        try:return runtime.learning.update(None,identifier,body.enabled)
        except ValueError:raise HTTPException(404,'经验不存在') from None

    @app.delete('/api/experiences/{identifier}')
    def delete_any_experience(identifier:str):
        try:runtime.learning.delete(None,identifier)
        except ValueError:raise HTTPException(404,'经验不存在') from None
        return {'deleted':True}

    @app.get("/api/status")
    def status():
        return {"permission_mode": settings.permission_mode, "mode": settings.mode, "model": settings.model, "configured": bool(settings.api_key), "base_url": settings.base_url, "tools": tools.catalog(), "skills": skills.summary(), "max_steps": settings.max_steps, "goal_block_cap":settings.goal_block_cap,"context_chars": settings.context_chars, "sandbox": {"default_mode":"host" if settings.permission_mode == "full" else "sandbox", "backend":"windows-appcontainer", "supported":os.name == "nt", "network":settings.permission_mode == "full","host_requires_approval":settings.permission_mode != "full"}, "scheduler": runtime.scheduler.status()}

    @app.get("/api/sessions")
    def sessions():
        return store.sessions()

    @app.post("/api/sessions")
    def new_session():
        return store.create_session()

    @app.delete("/api/sessions/{session}")
    async def delete_session(session: str):
        require(session)
        if session in runtime.active or session in runtime.uploading:
            raise HTTPException(409, "任务正在运行或上传中，请先结束操作再删除。")
        if not store.delete_session(session):
            raise HTTPException(404, "会话不存在或已删除")
        runtime.scheduler.remove_session(session)
        return {"deleted": True, "recoverable": False}

    @app.get("/api/sessions/{session}")
    def get_session(session: str):
        require(session)
        return {"messages": store.messages(session), "events": store.events(session), "tasks": store.tasks(session), "memory": store.memory(session), "running": session in runtime.active, "approvals": runtime.pending(session), "local_folder":uploads.local_folder(session), "attachments":uploads.records(session), "crons": runtime.scheduler.list_jobs(session),'goal':runtime.goals.status(session)}

    @app.get('/api/sessions/{session}/memory')
    async def get_memory(session:str):
        require(session)
        return {'memory':store.memory(session)}

    @app.put('/api/sessions/{session}/memory')
    async def edit_memory(session:str,body:MemoryEdit):
        require(session)
        if session in runtime.active:
            raise HTTPException(409,'当前会话有任务运行，请结束或停止后再保存备忘录。')
        try:content=store.edit_memory(session,body.content,body.expected)
        except LookupError:raise HTTPException(404,'会话不存在') from None
        except ValueError as error:raise HTTPException(409,str(error)) from None
        return {'saved':True,'memory':content}

    @app.get('/api/sessions/{session}/goal')
    async def get_goal(session: str):
        require(session)
        return {'goal':runtime.goals.status(session)}

    @app.post('/api/sessions/{session}/goal')
    async def set_goal(session: str, body: GoalRequest):
        require(session)
        try:
            return {'run_id':runtime.goals.start(session,body.condition),'goal':runtime.goals.status(session)}
        except ValueError as error:
            raise HTTPException(409,str(error))

    @app.post('/api/sessions/{session}/goal/control')
    async def goal_control(session: str, body: GoalAction):
        require(session)
        try:
            return await runtime.goals.control(session,body.action)
        except ValueError as error:
            raise HTTPException(409,str(error))

    @app.get("/api/sessions/{session}/crons")
    async def list_crons(session: str):
        require(session)
        return {"crons": runtime.scheduler.list_jobs(session)}

    @app.post("/api/sessions/{session}/crons")
    async def schedule_cron(session: str, body: CronSchedule):
        require(session)
        try:
            return runtime.scheduler.schedule(session, **body.model_dump())
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.delete("/api/sessions/{session}/crons/{job_id}")
    async def cancel_cron(session: str, job_id: str):
        require(session)
        try:
            return runtime.scheduler.cancel(session, job_id)
        except ValueError as error:
            raise HTTPException(404, str(error))

    @app.post("/api/folders/pick")
    async def choose_folder():
        if picker_lock.locked():
            raise HTTPException(409, "目录选择窗口已打开，请先完成选择")
        async with picker_lock:
            try:
                return {"path":await pick_folder()}
            except (ValueError, OSError, asyncio.TimeoutError):
                raise HTTPException(400, "目录选择未完成，请重试或直接粘贴文件夹路径")

    @app.post("/api/sessions/{session}/folder")
    async def bind_folder(session: str, body: Folder):
        require(session)
        if session in runtime.active or session in runtime.uploading:
            raise HTTPException(409, "任务正在运行或上传中，请稍后再选择文件夹")
        try:
            return uploads.bind_folder(session, body.path)
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error))

    @app.post("/api/sessions/{session}/uploads")
    async def upload_files(session: str, files: list[UploadFile] = File(...), paths: list[str] = Form(...)):
        require(session)
        if session in runtime.active or session in runtime.uploading:
            raise HTTPException(409, "任务正在运行或上传中，请稍后再上传。")
        runtime.uploading.add(session)
        try:
            items = await uploads.receive(session, files, paths)
            return {"files": items}
        except FileExistsError as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(400, str(error))
        except OSError:
            raise HTTPException(500, "无法保存上传内容，请检查文件名或磁盘空间。")
        finally:
            runtime.uploading.discard(session)

    @app.get("/api/sessions/{session}/files")
    async def files(session: str, path: str = ""):
        require(session)
        try:
            return uploads.scan(session, path)
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error))

    @app.get("/api/sessions/{session}/content")
    async def download(session: str, path: str = "", attachment: str | None = None):
        require(session)
        try:
            target = uploads.attachment_path(session,attachment) if attachment else uploads.tools(session).path(uploads.relative(path))
            if not target.is_file():
                raise HTTPException(404, "文件不存在")
            return FileResponse(target, media_type="application/octet-stream", filename=target.name,
                                headers={"X-Content-Type-Options":"nosniff", "Cache-Control":"no-store"})
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.get("/api/sessions/{session}/images/{attachment}")
    async def preview_image(session: str, attachment: str):
        require(session)
        record = next((item for item in uploads.records(session) if item["id"]==attachment), None)
        if not record or record["mime"] not in IMAGE_MIMES.values():
            raise HTTPException(404, "图片不存在")
        target = uploads.attachment_path(session,record["id"])
        if not target.is_file():
            raise HTTPException(404, "图片不存在")
        return FileResponse(target, media_type=record["mime"], headers={"X-Content-Type-Options":"nosniff", "Cache-Control":"no-store"})

    @app.post("/api/sessions/{session}/runs")
    async def run(session: str, body: Chat):
        require(session)
        try:
            text = body.message.strip()
            if text == '/goal' or text.startswith('/goal '):
                command = text[5:].strip()
                if command.lower() in {'','pause','resume','clear','stop','off','reset','none','cancel'}:
                    if body.attachments:
                        raise ValueError('目标控制命令不能携带附件')
                    if not command:
                        return {'run_id':None,'goal':runtime.goals.status(session),'message':'目标状态已更新'}
                    action = command.lower() if command.lower() in {'pause','resume'} else 'clear'
                    return await runtime.goals.control(session,action)
                return {'run_id':runtime.goals.start(session,command,body.attachments),'goal':runtime.goals.status(session)}
            if body.goal_enabled:
                condition = body.goal_condition.strip() or text
                return {'run_id':runtime.goals.start(session,condition,body.attachments,message=text),
                        'goal':runtime.goals.status(session)}
            return {"run_id": runtime.start(session, text, body.attachments, goal_enabled=body.goal_enabled is not False)}
        except ValueError as error:
            raise HTTPException(409, str(error))

    @app.post("/api/sessions/{session}/stop")
    async def stop(session: str):
        require(session)
        await runtime.stop(session)
        return {"stopped": True}

    @app.post("/api/sessions/{session}/approvals/{approval_id}")
    async def approve(session: str, approval_id: str, body: Approval):
        require(session)
        try:
            runtime.approve(session, approval_id, body.allow)
            return {"accepted": True}
        except ValueError as error:
            raise HTTPException(409, str(error))

    @app.get("/api/sessions/{session}/stream")
    async def stream(session: str, request: Request, after: int = 0):
        require(session)
        async def events():
            cursor = after
            waiting_sent = False
            while True:
                if await request.is_disconnected():
                    break
                for event in store.events(session, cursor):
                    if event["seq"] > cursor:
                        cursor = event["seq"]
                        yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if session not in runtime.active:
                    if not runtime.scheduler.list_jobs(session):
                        yield "event: idle\ndata: {}\n\n"
                        break
                    if not waiting_sent:
                        yield "event: waiting\ndata: {}\n\n"
                        waiting_sent = True
                else:
                    waiting_sent = False
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/skills/{name}")
    def skill(name: str):
        try:
            detail=skills.describe(name)
            return {"name":name,"content":detail["instructions"],**detail}
        except ValueError as error:
            raise HTTPException(404, str(error))

    @app.get("/")
    def index():
        return FileResponse(settings.root / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=settings.root / "static"), name="static")
    return app


class Chat(BaseModel):
    goal_enabled: bool | None = None
    goal_condition: str = Field(default="",max_length=4000)
    message: str = Field(default="", max_length=20000)
    attachments: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.message.strip() and not self.attachments:
            raise ValueError("请输入内容或选择附件")
        return self


class MemoryEdit(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    content:str=Field(max_length=8000)
    expected:str=Field(max_length=8000)


class Approval(BaseModel):
    allow: bool


class GoalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    condition: str = Field(min_length=1,max_length=4000,pattern=r'\S')


class GoalAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['pause','resume','clear']


class Folder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)


class StorageDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[str] = Field(min_length=1, max_length=500)


class PermissionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permission_mode: Literal["approval", "full"]


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = None

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        from urllib.parse import urlsplit
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if (parts.scheme not in {"https", "http"} or not parts.hostname or parts.username
                or parts.password or parts.query or parts.fragment or any(c.isspace() for c in value)):
            raise ValueError("Invalid API endpoint")
        if parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Remote endpoints require HTTPS")
        _ = parts.port  # Validate numeric port range as well.
        return value

    @field_validator("model")
    @classmethod
    def valid_model(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Invalid model ID")
        return value

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        if value is None or not value.get_secret_value().strip():
            return None
        key = value.get_secret_value().strip()
        if len(key) > 4096 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
            raise ValueError("Invalid API credential")
        return SecretStr(key)


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765)

