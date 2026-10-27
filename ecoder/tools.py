import asyncio
import difflib
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .store import uid


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PathArgs(Args):
    path: str = "."


class ReadArgs(Args):
    path: str
    offset: int = Field(default=1, ge=1)
    limit: int = Field(default=200, ge=1, le=500)


class SearchArgs(Args):
    query: str = Field(min_length=1, max_length=200)
    path: str = "."


class WriteArgs(Args):
    path: str
    content: str = Field(max_length=200000)


class EditArgs(Args):
    path: str
    old_text: str = Field(min_length=1)
    new_text: str


class ExecArgs(Args):
    execution_mode: Literal["sandbox", "host"] = "sandbox"
    argv: list[str] = Field(min_length=1, max_length=50)
    timeout: int = Field(default=30, ge=1, le=120)


class SkillArgs(Args):
    name: str


class TaskCreate(Args):
    title: str = Field(min_length=1, max_length=200)
    dependencies: list[str] = Field(default_factory=list)


class TaskUpdate(Args):
    id: str
    status: Literal["pending", "in_progress", "completed"]


class MemoryArgs(Args):
    content: str = Field(max_length=8000)


class SubagentArgs(Args):
    prompt: str = Field(min_length=1, max_length=12000, pattern=r"\S")
    max_steps: int = Field(default=30, ge=1, le=30)


class CronSchedule(Args):
    cron: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=12000, pattern=r"\S")
    recurring: bool = True
    durable: bool = True


class CronCancel(Args):
    job_id: str = Field(min_length=1, max_length=80)


SPECS = {
    "list_files": (PathArgs, "列出工作区目录（最多 150 项）", "read"),
    "read_file": (ReadArgs, "按行读取 UTF-8 文件", "read"),
    "search_code": (SearchArgs, "在工作区文本文件中搜索字面量，返回文件和行号", "read"),
    "write_file": (WriteArgs, "创建或覆盖文件；需用户批准 diff", "approval"),
    "edit_file": (EditArgs, "精确替换唯一文本；需用户批准 diff", "approval"),
    "run_command": (ExecArgs, "执行参数数组命令，始终需批准。默认 execution_mode=sandbox：Windows AppContainer、禁止联网、临时工作区，仅成功时同步文件；下载依赖/安装技能等联网或工作区外操作必须显式使用 host 并申请主机权限。失败不得自动改成 host", "approval"),
    "load_skill": (SkillArgs, "按需读取技能全文、资源索引和本机运行时路径", "read"),
    "create_task": (TaskCreate, "创建有依赖的任务，依赖必须是已存在的任务 ID", "state"),
    "update_task": (TaskUpdate, "更新任务；依赖完成后才能开始或完成", "state"),
    "list_tasks": (Args, "查看当前会话任务依赖及状态", "read"),
    "save_memory": (MemoryArgs, "覆盖当前会话的持久备忘录；保存用户约束和已验证事实", "state"),
    "sub_agent": (SubagentArgs, "同步委派明确子任务给独立上下文的子 Agent，仅返回最终结论；不继承聊天历史，需在 prompt 提供必要背景和文件路径；子 Agent 写入和命令仍需审批", "delegate"),
    "schedule_cron": (CronSchedule, "按五段式 Cron 创建本会话定时 prompt，北京时间 Asia/Shanghai；默认周期执行且持久化，recurring=false 表示下次匹配仅交付一次；服务需保持运行，操作仍需审批", "state"),
    "list_crons": (Args, "列出当前会话的定时任务、待交付状态及触发记录", "read"),
    "cancel_cron": (CronCancel, "取消当前会话的定时任务及排队交付；已启动的运行请另用停止按钮", "state"),
}
SUBAGENT_TOOLS = frozenset({"list_files", "read_file", "search_code", "write_file", "edit_file", "run_command", "load_skill"})
SKIP = {".git", ".venv", "node_modules", "__pycache__", ".ecoder", ".tools"}


class Tools:
    def __init__(self, workspace, store, skills, attachments=()):
        self.root = workspace.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store, self.skills = store, skills
        self.attachments = frozenset(attachments)

    def catalog(self):
        return [{"name": name, "description": desc, "permission": perm, "schema": model.model_json_schema()} for name, (model, desc, perm) in SPECS.items()]

    def definitions(self, names=None):
        return [{"type": "function", "function": {"name": tool["name"], "description": tool["description"], "parameters": tool["schema"]}} for tool in self.catalog() if names is None or tool["name"] in names]

    def validate(self, name, args):
        if name not in SPECS:
            raise ValueError(f"未知工具: {name}")
        return SPECS[name][0].model_validate(args).model_dump()

    def path(self, value, read_only=False):
        path = (self.root / value).resolve()
        if Path(value).is_absolute() and path in self.attachments:
            return path
        if read_only and Path(value).is_absolute() and self.skills.readable(path):
            return path
        if not path.is_relative_to(self.root):
            raise ValueError("路径越过工作区边界")
        relative = path.relative_to(self.root)
        if any(part.casefold() in SKIP or part.casefold() == ".env" or part.casefold().startswith(".env.") for part in relative.parts):
            raise ValueError("拒绝访问环境密钥或内部目录")
        return path

    def preview(self, name, args):
        if name == "run_command":
            mode = args.get("execution_mode", "sandbox")
            return {"command": args["argv"], "execution_mode": mode,
                    "warning": "主机执行：可访问工作区外的资源和网络，请确认需要此权限。" if mode == "host" else
                    "沙箱执行：Windows AppContainer，禁止联网；只同步成功命令的工作区文件变更，失败或超时不保留变更。"}
        path = self.path(args["path"])
        if path.exists() and path.stat().st_size > 200000:
            raise ValueError("修改目标超过 200 KB，请使用更小的文件")
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if name == "edit_file":
            if old is None or old.count(args["old_text"]) != 1:
                raise ValueError("old_text 必须在文件中恰好出现一次")
            new = old.replace(args["old_text"], args["new_text"], 1)
        else:
            new = args["content"]
        diff = "".join(difflib.unified_diff((old or "").splitlines(keepends=True), new.splitlines(keepends=True), fromfile=f"a/{args['path']}", tofile=f"b/{args['path']}"))
        return {"path": args["path"], "diff": diff or "（内容相同）", "before": old, "after": new}

    async def execute(self, session, name, args, prepared=None):
        if name == "list_files":
            path = self.path(args["path"])
            entries = []
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    self.path(str(child))
                except ValueError:
                    continue
                entries.append({"name": child.name, "directory": child.is_dir()})
                if len(entries) == 150:
                    break
            return entries
        if name == "read_file":
            path = self.path(args["path"],read_only=True)
            if path.stat().st_size > 2_000_000:
                raise ValueError("文件超过 2 MB，请缩小目标")
            lines = path.read_text(encoding="utf-8").splitlines()
            start = args["offset"] - 1
            return {"path": args["path"], "total_lines": len(lines), "text": "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines[start:start+args["limit"]], start))}
        if name == "search_code":
            return await asyncio.to_thread(self.search, args)
        if name in {"write_file", "edit_file"}:
            if prepared is None:
                raise ValueError("修改缺少已审批的快照")
            path = self.path(args["path"])
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != prepared["before"]:
                raise ValueError("文件在审批期间已改变，请重新生成 diff 并申请批准")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(prepared["after"], encoding="utf-8")
            return {"path": args["path"], "bytes": len(prepared["after"].encode("utf-8")), "diff": prepared["diff"]}
        if name == "run_command":
            if prepared is None:
                raise ValueError("命令缺少审批")
            return await self.command(args)
        if name == "load_skill":
            return self.skills.describe(args["name"])
        if name == "list_tasks":
            return self.store.tasks(session)
        if name == "create_task":
            tasks = {task["id"]: task for task in self.store.tasks(session)}
            if any(dep not in tasks for dep in args["dependencies"]):
                raise ValueError("依赖任务不存在于当前会话")
            # Edges only point to existing immutable nodes: cycles cannot be introduced.
            task = {"id": uid()[:12], "title": args["title"], "dependencies": list(dict.fromkeys(args["dependencies"])), "status": "pending"}
            self.store.save_task(session, task)
            return task
        if name == "update_task":
            tasks = {task["id"]: task for task in self.store.tasks(session)}
            task = tasks.get(args["id"])
            if task is None:
                raise ValueError("任务不存在于当前会话")
            if args["status"] != "pending" and any(tasks[d]["status"] != "completed" for d in task["dependencies"]):
                raise ValueError("依赖尚未完成")
            if task["status"] == "completed" and args["status"] != "completed":
                raise ValueError("已完成任务不能回退；请创建新的修复任务")
            task["status"] = args["status"]
            self.store.save_task(session, task)
            return task
        if name == "save_memory":
            self.store.save_memory(session, args["content"])
            return {"saved": True}
        raise ValueError("工具未实现")

    def search(self, args):
        start, hits, scanned = time.monotonic(), [], 0
        root = self.path(args["path"])
        for parent, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP and not (Path(parent) / d).is_symlink()]
            for filename in files:
                scanned += 1
                if scanned > 3000 or time.monotonic() - start > 5:
                    return {"matches": hits, "truncated": True}
                try:
                    path = self.path(str(Path(parent) / filename))
                    if path.stat().st_size > 500000:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, ValueError, UnicodeError):
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if args["query"].lower() in line.lower():
                        hits.append({"path": str(path.relative_to(self.root)), "line": number, "text": line[:300]})
                        if len(hits) == 80:
                            return {"matches": hits, "truncated": True}
        return {"matches": hits, "truncated": False}

    async def command(self, args):
        if args.get("execution_mode", "sandbox") == "sandbox":
            from .sandbox import command
            return await command(self, args)
        if args.get("execution_mode") != "host":
            raise ValueError("未知执行模式；未执行命令")
        return await self.host_command(args)

    async def host_command(self, args):
        # No shell, no inherited API credentials. Approval is the trust boundary,
        # not a regex masquerading as an OS sandbox.
        env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
        # Skill installation belongs to this E_coder instance, independent of
        # the user's connected workspace or inherited Codex configuration.
        env["ECODER_SKILLS_DIR"] = str(self.skills.root)
        proc = await asyncio.create_subprocess_exec(*args["argv"], cwd=self.root, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output = bytearray()

        async def drain():
            while chunk := await proc.stdout.read(4096):
                if len(output) < 24000:
                    output.extend(chunk[:24000-len(output)])
            await proc.wait()

        try:
            await asyncio.wait_for(drain(), args["timeout"])
        except (TimeoutError, asyncio.CancelledError):
            if proc.returncode is None:
                if os.name == "nt":
                    killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(proc.pid), "/T", "/F", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    await killer.wait()
                else:
                    proc.kill()
                await proc.wait()
            raise
        return {"exit_code": proc.returncode, "output": output.decode("utf-8", errors="replace"), "output_limit": 24000, "execution_mode": "host", "sandbox": None}
