"""Desktop session state, streaming jobs and explicit local-file grants."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import json
import mimetypes
from pathlib import Path
import secrets
import threading
import time

from ..app import AppContext
from ..config import load_config
from ..desktop.service import DesktopService
from ..desktop.actions import execute
from ..codex.control import RunControl
from ..tools.confirm import ConfirmationBroker
from ..store.conversation import Conversations
from ..store.attachments import Attachments
from ..store.attachment_workspace import AssetStore
from ..attachments import IMAGES, VIDEOS, managed_path
from ..attachment_archives import ARCHIVES


def file_kind(name):
    suffix = Path(name).suffix.lower()
    return "image" if suffix in IMAGES else "video" if suffix in VIDEOS else "archive" if suffix in ARCHIVES else "document"


@dataclass
class Upload:
    id: str
    path: Path
    temporary: bool = False

    def public(self):
        return {"id": self.id, "name": self.path.name, "size": self.path.stat().st_size,
                "kind": file_kind(self.path.name), "status": "ready"}


@dataclass
class Job:
    id: str
    kind: str
    conversation_id: int | None = None
    task: asyncio.Task | None = None
    control: RunControl = field(default_factory=RunControl)
    broker: ConfirmationBroker = field(default_factory=ConfirmationBroker)
    state: str = "running"
    message: str = "正在准备…"
    answer: str = ""
    reasoning: str = ""
    ready: bool = False
    tools: list = field(default_factory=list)
    confirmations: dict = field(default_factory=dict)
    events: deque = field(default_factory=lambda: deque(maxlen=256))
    started_at: float = field(default_factory=time.time)

    def public(self):
        return {k: getattr(self, k) for k in ("id", "kind", "conversation_id", "state", "message", "answer", "reasoning", "ready", "tools", "confirmations", "started_at")}


class Gateway:
    def __init__(self, paths, *, runner=execute):
        self.paths, self.service, self.runner = paths, DesktopService(paths), runner
        self.token = secrets.token_urlsafe(32)
        self.job = None
        self.subscribers = set()
        self.uploads = {}
        self.last_hot = None
        self.lock = threading.Lock()
        self.sequence = 0
        self.native = False
        self.bridge_js = ""
        self.upload_root = paths.state_dir / "html-uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)

    def register(self, paths, *, temporary=False):
        results = []
        with self.lock:
            for value in paths:
                path = Path(value).resolve()
                if not path.is_file():
                    continue
                item = Upload(secrets.token_hex(16), path, temporary)
                self.uploads[item.id] = item
                results.append(item.public())
        return results

    def upload(self, identifier):
        with self.lock:
            item = self.uploads.get(identifier)
        if item is None:
            raise ValueError("文件已失效，请重新添加")
        return item

    def discard(self, identifier):
        with self.lock:
            item = self.uploads.get(identifier)
        if item and item.temporary and item.path.resolve().is_relative_to(self.upload_root.resolve()):
            try:
                item.path.unlink(missing_ok=True)
            except PermissionError:
                # A cancelled import may still be finishing its streaming copy.
                # Retain the grant for a later cleanup; never affect the original.
                return False
            try:
                item.path.parent.rmdir()
            except OSError:
                pass
        with self.lock:
            self.uploads.pop(identifier, None)
        return True

    def preferences(self):
        file = self.paths.state_dir / "html-preferences.json"
        try:
            return json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"theme": "light", "last_conversation": None}

    def save_preferences(self, values):
        old = self.preferences()
        if values.get("theme") in ("light", "dark", "system"):
            old["theme"] = values["theme"]
        if "last_conversation" in values:
            value = values["last_conversation"]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError("会话编号错误")
            old["last_conversation"] = value
        file = self.paths.state_dir / "html-preferences.json"
        temporary = file.with_suffix(".tmp")
        temporary.write_text(json.dumps(old), encoding="utf-8")
        temporary.replace(file)
        return old

    def recent(self):
        from ..db.connect import Database
        with Database.open(self.paths.db_path, read_only=True) as db:
            return Conversations(db).recent()

    def bootstrap(self):
        overview = self.service.overview()
        return {"overview": overview, "settings": overview["settings"], "conversations": self.recent(),
                "profile": self.service.enterprise_workspace()["profile"], "preferences": self.preferences(),
                "job": self.job.public() if self.job else None, "native": self.native}

    def publish(self, event):
        job = self.job
        if job is None:
            return
        event = dict(event)
        event_type = event.get("type")
        if event.get("conversation_id"):
            job.conversation_id = event["conversation_id"]
        if event.get("message"):
            job.message = str(event["message"])
        if event_type == "answer_delta":
            job.answer += event.get("delta", "")
        elif event_type == "thinking":
            job.reasoning += event.get("delta", "")
        elif event_type == "codex_ready":
            job.ready = bool(event.get("ready"))
        elif event_type == "steer_done" and event.get("accepted"):
            job.answer = ""
        elif event_type == "tool":
            if event.get("phase") == "start":
                job.tools.append({"tool": event["tool"], "name": event.get("name", event["tool"]), "status": "running"})
                job.message = event.get("name", "工具") + "执行中…"
            elif event.get("phase") == "done":
                for item in reversed(job.tools):
                    if item["tool"] == event["tool"] and item["status"] == "running":
                        item.update(status="complete" if event.get("ok") else "failed", summary=event.get("summary", ""))
                        break
                job.message = event.get("summary") or "继续处理…"
            elif event.get("phase") == "confirm":
                job.confirmations[event["request_id"]] = event
            elif event.get("phase") == "confirm_done":
                job.confirmations.pop(event["request_id"], None)
        self.sequence += 1
        message = {"sequence": self.sequence, "job_id": job.id, "conversation_id": job.conversation_id, **event}
        job.events.append(message)
        for queue in tuple(self.subscribers):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "snapshot", "job": job.public()})
            else:
                queue.put_nowait(message)

    async def start(self, kind, options=None):
        if self.job and self.job.state == "running":
            raise ValueError("已有任务正在执行，可追加要求或先停止")
        options = dict(options or {})
        if kind not in ("chat", "login", "collect", "benchmark", "comments", "profile", "review", "plan", "enterprise", "chat_fork", "chat_compact", "gallery", "hot"):
            raise ValueError("未知任务类型")
        identifiers = options.pop("upload_ids", [])
        uploads = [self.upload(value) for value in identifiers]
        cid = options.get("conversation_id")
        if kind == "chat":
            request = str(options.get("request") or "").strip()
            if not request and uploads:
                request = "请阅读并分析这些附件，概括主要内容与需要注意的问题。"
            if not request or len(request) > 6000:
                raise ValueError("请输入消息（不超过6000字）")
            if not self.service.settings()["configured"]:
                raise ValueError("请先在设置中保存 DeepSeek Key")
            if cid is None:
                with AppContext.create(load_config(self.paths)) as ctx:
                    cid = Conversations(ctx.db).create(request)
            else:
                self.service.conversation(int(cid))
            options.update(request=request, conversation_id=cid, attachment_paths=[str(u.path) for u in uploads])
            self.save_preferences({"last_conversation": cid})
        self.job = Job(secrets.token_hex(12), kind, cid)
        job = self.job
        options.update(broker=job.broker, control=job.control)
        self.publish({"type": "started", "kind": kind, "message": "正在准备任务…"})

        async def run():
            try:
                if kind == "gallery":
                    result = await self._gallery(options)
                elif kind == "hot":
                    result = await asyncio.to_thread(self.service.hot_board)
                    self.last_hot = result
                    result = {"message": "热点已更新", "hot": result}
                else:
                    result = await self.runner(self.paths, kind, self.publish, options)
                job.state = "failed" if result.get("failed") else "complete"
                job.message = result.get("message") or "任务已完成"
                if result.get("conversation"):
                    job.conversation_id = result["conversation"]["id"]
                    if kind in ("chat", "chat_fork", "chat_compact"):
                        self.save_preferences({"last_conversation": job.conversation_id})
                self.publish({"type": "result", "result": result, "state": job.state, "message": job.message})
            except asyncio.CancelledError:
                job.state, job.message = "cancelled", "已停止，执行记录已保存"
                self.publish({"type": "result", "state": "cancelled", "result": {"cancelled": True}, "message": job.message})
            except Exception as exc:
                job.state = "failed"
                detail = str(exc)
                key = load_config(self.paths).llm.api_key
                job.message = detail.replace(key, "[密钥]") if key else detail
                self.publish({"type": "error", "state": "failed", "message": job.message})
            finally:
                job.ready = False
                await job.control.close()
                for identifier in identifiers:
                    self.discard(identifier)
        job.task = asyncio.create_task(run())
        return job.public()

    async def _gallery(self, options):
        from ..attachment_workspace import build_workspace, refresh_attachment
        from ..store.workflow import WorkflowLease
        stop = threading.Event()
        with AppContext.create(load_config(self.paths)) as ctx, WorkflowLease(self.paths.state_dir):
            item = Attachments(ctx.db).get(options["attachment_id"], options["conversation_id"])
            if not item:
                raise ValueError("找不到该会话附件")
            loop = asyncio.get_running_loop()
            emit = lambda e: loop.call_soon_threadsafe(self.publish, e)
            worker = asyncio.create_task(asyncio.to_thread(build_workspace, ctx, item, emit, stop))
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                stop.set()
                await worker
                raise
            refresh_attachment(ctx, item)
            return {"message": "素材缩略图已就绪", "conversation": Conversations(ctx.db).get(options["conversation_id"])}

    async def cancel(self):
        if self.job and self.job.state == "running" and self.job.task:
            self.job.task.cancel()
            return {"ok": True}
        return {"ok": False}

    async def steer(self, text):
        if not self.job or self.job.state != "running" or not self.job.ready or not text.strip():
            raise ValueError("当前任务暂不能追加要求")
        if not self.job.control.submit(text):
            raise ValueError("追加要求未送达，请稍后重试")
        return {"ok": True}

    async def close(self):
        await self.cancel()
        if self.job and self.job.task:
            await asyncio.gather(self.job.task, return_exceptions=True)

    def library(self, offset=0, count=60, query=""):
        from ..db.connect import Database
        with Database.open(self.paths.db_path, read_only=True) as db:
            rows = db.rows_as_dicts("SELECT id,conversation_id,name,kind,size,status,created_at FROM attachments WHERE name LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                   ("%" + query + "%", count, offset))
            total = db.scalar("SELECT COUNT(*) FROM attachments WHERE name LIKE ?", ("%" + query + "%",))
            for row in rows:
                row["workspace"] = AssetStore(db).progress(row["id"])
            return {"rows": rows, "total": total, "offset": offset}

    def assets(self, attachment_id, *, query="", kind="", offset=0, count=60):
        from ..db.connect import Database
        with Database.open(self.paths.db_path, read_only=True) as db:
            attachment = db.query_one("SELECT * FROM attachments WHERE id=?", (attachment_id,))
            if not attachment:
                raise ValueError("附件不存在")
            all_assets = AssetStore(db).assets(attachment_id)
            matches = [a for a in all_assets if (not kind or a["kind"] == kind) and query.lower() in (a["name"] + a["observation"]).lower()]
            return {"attachment": {k: attachment[k] for k in ("id", "name", "conversation_id")},
                    "progress": AssetStore(db).progress(attachment_id), "rows": matches[offset:offset + count], "total": len(matches)}

    def resolve_file(self, identifier, asset_id=None, variant="source"):
        from ..db.connect import Database
        from ..tools.workspace import artifact_path
        with Database.open(self.paths.db_path, read_only=True) as db:
            if identifier.startswith("W"):
                item = db.query_one("SELECT * FROM workspace_artifacts WHERE id=?", (identifier[1:],))
                if not item:
                    raise ValueError("产物不存在")
                return artifact_path(self.paths, item["relative_path"]), item["name"]
            item = db.query_one("SELECT * FROM attachments WHERE id=?", (identifier,))
            if not item:
                raise ValueError("附件不存在")
            if asset_id:
                asset = AssetStore(db).get(identifier, asset_id)
                if not asset:
                    raise ValueError("素材不存在")
                relative = asset["thumbnail_path"] if variant == "thumbnail" else asset["source_path"]
                if not relative:
                    raise ValueError("素材尚未展开")
                return managed_path(self.paths, relative), asset["name"]
            return managed_path(self.paths, item["relative_path"]), item["name"]
