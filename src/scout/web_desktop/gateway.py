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
from ..desktop.update import (current_version, download as download_update, fetch_latest,
                              install_dir, is_newer, launch_updater)
from ..codex.control import RunControl
from ..tools.confirm import ConfirmationBroker
from ..store.conversation import Conversations
from ..store.attachments import Attachments
from ..store.attachment_workspace import AssetStore
from ..attachments import IMAGES, VIDEOS, managed_path
from ..attachment_archives import ARCHIVES
from ..work_media import UpstreamUnavailable, WorkMediaBusy, WorkMediaError, url_expired


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
        self.hot_task = None
        self.hot_error = ""
        self.lock = threading.Lock()
        self.sequence = 0
        self.native = False
        self.upload_root = paths.state_dir / "html-uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        from ..work_media import WorkMedia
        self.work_media = WorkMedia(paths)
        self._work_locks: dict[str, asyncio.Lock] = {}
        self._hot_locks: dict[str, asyncio.Lock] = {}
        self.update_info = None
        self.update_checked_at = 0.0
        self.update_download = {"state": "idle", "received": 0, "total": 0, "version": "",
                                "error": "", "archive": "", "verified": False}
        self._update_lock = threading.Lock()

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
        if "update_auto" in values:
            old["update_auto"] = bool(values["update_auto"])
        if "update_skipped" in values:
            value = values["update_skipped"]
            if value is not None and not isinstance(value, str):
                raise ValueError("跳过版本号错误")
            old["update_skipped"] = str(value or "").lstrip("vV")
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

    # ── 作品媒体 ────────────────────────────────────────────

    def work_detail(self, aweme_id):
        return self.work_media.detail(aweme_id)

    # ── 应用内更新 ──────────────────────────────────────────

    def update_status(self, *, check=False, timeout=6.0):
        if check:
            info = fetch_latest(timeout=timeout)
            with self._update_lock:
                self.update_info = info
                self.update_checked_at = time.time()
        prefs = self.preferences()
        with self._update_lock:
            info = self.update_info
            progress = dict(self.update_download)
            checked_at = self.update_checked_at
        version = str((info or {}).get("version") or "")
        return {
            "current": current_version(),
            "installed": install_dir() is not None,
            "auto_check": prefs.get("update_auto") is not False,
            "skipped": str(prefs.get("update_skipped") or ""),
            "checked_at": checked_at,
            "latest": info,
            "newer": bool(info and is_newer(version)),
            "download": progress,
        }

    def start_update_download(self):
        status = self.update_status()
        if not status["latest"]:
            status = self.update_status(check=True)
        info = status["latest"]
        if not info:
            raise ValueError("无法获取版本信息，请检查网络后重试")
        if not status["newer"]:
            raise ValueError("已是最新版本")
        if not info.get("zip_url"):
            raise ValueError("更新源没有提供下载地址")
        version = str(info.get("version") or "")
        with self._update_lock:
            if self.update_download["state"] == "downloading":
                return dict(self.update_download)
            if self.update_download["state"] == "ready" and self.update_download["version"] == version:
                return dict(self.update_download)
            self.update_download = {"state": "downloading", "received": 0,
                                    "total": int(info.get("zip_size") or 0),
                                    "version": version, "error": "", "archive": "",
                                    "verified": False}
        target = self.paths.root / "updates" / f"yuanjing-{version}.zip"

        def report(received, total):
            with self._update_lock:
                self.update_download["received"] = received
                if total:
                    self.update_download["total"] = total

        expected = str(info.get("sha256") or "").lower()

        def run():
            ok = download_update(str(info.get("zip_url") or ""), target, timeout=120,
                                 sha256=expected, progress=report)
            with self._update_lock:
                if ok:
                    self.update_download.update(state="ready", archive=str(target),
                                                received=target.stat().st_size,
                                                verified=bool(expected))
                else:
                    self.update_download.update(
                        state="failed", error="下载失败或校验不通过，请稍后重试，或到发布页手动下载")

        threading.Thread(target=run, daemon=True).start()
        return self.update_status()

    def apply_update(self):
        with self._update_lock:
            state = dict(self.update_download)
        if state.get("state") != "ready":
            raise ValueError("更新包尚未就绪")
        if not state.get("verified"):
            raise ValueError("更新源没有提供 sha256，无法自动安装，请到发布页手动下载")
        folder = install_dir()
        if folder is None:
            raise ValueError("源码运行模式不支持自动替换，请到发布页下载新版本")
        archive = Path(str(state.get("archive") or ""))
        if not archive.is_file():
            raise ValueError("更新包已丢失，请重新下载")
        if not launch_updater(archive, folder):
            raise ValueError("无法启动更新脚本，请到发布页手动下载")
        with self._update_lock:
            self.update_download["state"] = "applying"
        return {"started": True}

    # ── 热点视频 ────────────────────────────────────────────

    def hot_video_items(self, sentence_id):
        from ..db.connect import Database
        from ..store.hot import HotVideoLinks
        with Database.open(self.paths.db_path, read_only=True) as db:
            store = HotVideoLinks(db)
            return {"items": store.listing(sentence_id), "fetched_at": store.fetched_at(sentence_id)}

    def _hot_lock(self, sentence_id):
        lock = self._hot_locks.get(sentence_id)
        if lock is None:
            lock = self._hot_locks[sentence_id] = asyncio.Lock()
        return lock

    async def hot_videos(self, sentence_id, *, refresh=False):
        if not refresh:
            cached = await asyncio.to_thread(self.hot_video_items, sentence_id)
            if cached["items"]:
                return cached
        async with self._hot_lock(str(sentence_id)):
            if not refresh:
                cached = await asyncio.to_thread(self.hot_video_items, sentence_id)
                if cached["items"]:
                    return cached
            from ..collect.hot_video import fetch_hot_videos
            from ..session.lock import ProfileLockBusy
            ctx = AppContext.create(load_config(self.paths))
            try:
                try:
                    await fetch_hot_videos(ctx, sentence_id)
                except ProfileLockBusy as exc:
                    raise WorkMediaBusy("采集正在使用浏览器，请稍后再试") from exc
                except (ValueError, WorkMediaBusy):
                    raise
                except Exception as exc:
                    raise RuntimeError(f"获取热点视频失败：{exc}") from exc
            finally:
                if ctx.session is not None:
                    try:
                        await ctx.session.stop()
                    except Exception:
                        pass
                ctx.close()
        return await asyncio.to_thread(self.hot_video_items, sentence_id)

    async def send_hot_video(self, sentence_id, aweme_id, request=""):
        """把热点视频下载成附件，直接开一个工作台对话交给团队。"""
        from ..db.connect import Database
        from ..work_media import download
        url = await self.work_media_url(aweme_id)
        dest = self.paths.state_dir / "hot-videos" / f"{aweme_id}.mp4"
        await asyncio.to_thread(download, url, dest)
        uploads = self.register([dest])
        row = await asyncio.to_thread(self.work_media.row, aweme_id)
        with Database.open(self.paths.db_path, read_only=True) as db:
            topic = db.query_one(
                "SELECT word FROM hot_entries WHERE sentence_id = ? ORDER BY rowid DESC LIMIT 1",
                (str(sentence_id),))
            word = (topic["word"] if topic else "") or ""
        title = (row.get("description") or "未命名视频")[:80]
        prompt = str(request or "").strip() or (
            f"这是抖音热点「{word or '实时热点'}」下的视频《{title}》"
            f"（点赞 {row.get('digg_count') or 0}、评论 {row.get('comment_count') or 0}）。"
            "请先看视频画面，再回答三点：1) 画面和内容在讲什么；2) 它为什么可能上榜；"
            "3) 我们能怎么借势，给一个可以直接执行的选题。看不清的地方直接说看不清。"
        )
        await self.start("chat", {"request": prompt, "upload_ids": [item["id"] for item in uploads]})
        return {"conversation_id": self.job.conversation_id, "job": self.job.public()}

    def hot_refreshing(self):
        return bool(self.hot_task and not self.hot_task.done())

    def hot_status(self):
        return {"refreshing": self.hot_refreshing(), "error": self.hot_error}

    async def refresh_hot(self):
        """后台刷新热榜，不占用唯一的对话任务槽。"""
        if self.hot_refreshing():
            return self.hot_status()
        self.hot_error = ""

        async def run():
            try:
                result = await asyncio.to_thread(self.service.hot_board)
                self.last_hot = result
            except Exception as exc:      # noqa: BLE001
                self.hot_error = str(exc)[:200]
            finally:
                self.hot_task = None

        self.hot_task = asyncio.create_task(run())
        return self.hot_status()

    def insights(self):
        from ..db.connect import Database
        from ..store.insights import Insights
        with Database.open(self.paths.db_path, read_only=True) as db:
            return Insights(db, tz=load_config(self.paths).app.timezone).build()

    def _work_lock(self, aweme_id):
        lock = self._work_locks.get(aweme_id)
        if lock is None:
            lock = self._work_locks[aweme_id] = asyncio.Lock()
        return lock

    async def work_media_url(self, aweme_id):
        """返回当前可用的播放地址；过期就刷新。"""
        try:
            return await asyncio.to_thread(self.work_media.play_url, aweme_id)
        except WorkMediaError:
            return await self.refresh_work(aweme_id)

    async def refresh_work(self, aweme_id, *, force=False):
        from ..collect.work_detail import fetch_work
        from ..session.lock import ProfileLockBusy

        async with self._work_lock(aweme_id):
            row = await asyncio.to_thread(self.work_media.row, aweme_id)
            if not force and not url_expired(row):
                return str(row["play_url"])
            ctx = AppContext.create(load_config(self.paths))
            try:
                try:
                    work = await fetch_work(ctx, aweme_id)
                except ProfileLockBusy as exc:
                    raise WorkMediaBusy("采集正在使用浏览器，请稍后再试") from exc
                except WorkMediaError:
                    raise
                except Exception as exc:  # playwright 未安装、页面打不开等
                    raise UpstreamUnavailable(str(exc) or "刷新播放地址失败") from exc
            finally:
                if ctx.session is not None:
                    try:
                        await ctx.session.stop()
                    except Exception:
                        pass
                ctx.close()
            url = str(work.get("play_url") or "")
            if not url:
                raise UpstreamUnavailable("刷新后仍没有播放地址")
            return url

    def save_work(self, aweme_id):
        try:
            url = self.work_media.play_url(aweme_id)
        except WorkMediaError as exc:
            raise exc
        return self.work_media.save(aweme_id, url)

    def work_usage(self):
        return self.work_media.usage()

    def clear_work_media(self):
        return self.work_media.clear()

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
