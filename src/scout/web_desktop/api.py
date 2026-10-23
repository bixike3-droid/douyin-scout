"""Authenticated loopback API. File bytes stream; jobs reuse existing executors."""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import json
import mimetypes
import os
import subprocess
from pathlib import Path
import secrets
import sys

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .gateway import Gateway
from ..app import AppContext
from ..config import load_config
from ..db.connect import Database
from ..store.conversation import Conversations
from ..attachments import VIDEOS


def _frontend_dist() -> Path:
    """定位前端产物：源码在仓库根下，PyInstaller onedir 在 _internal/ 下。

    打包版里 __file__ 指向 <stage>/_internal/scout/web_desktop/api.py，
    parents[3] 会落到 <stage> 而数据放在 <stage>/_internal，所以必须两个都试。
    """
    here = Path(__file__).resolve()
    roots = [Path(getattr(sys, "_MEIPASS", here.parents[2]))]
    for parent in here.parents[:4]:
        roots.append(parent)
    for root in roots:
        candidate = root / "desktop-html" / "dist"
        if (candidate / "index.html").is_file():
            return candidate
    return here.parents[3] / "desktop-html" / "dist"


def create_app(paths, *, gateway=None, dist=None):
    gateway = gateway or Gateway(paths)
    with AppContext.create(load_config(paths)):
        pass
    dist = Path(dist) if dist else _frontend_dist()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await gateway.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gateway = gateway

    def authorized(token):
        return isinstance(token, str) and secrets.compare_digest(token, gateway.token)

    def same_origin(origin, base):
        """同源判定：完全一致，或者两边都是本机回环（Vite dev server 用不同端口代理过来）。"""
        if not origin:
            return True
        if origin.rstrip("/") == str(base).rstrip("/"):
            return True
        from urllib.parse import urlsplit
        left, right = urlsplit(origin).hostname, urlsplit(str(base)).hostname
        loopback = {"127.0.0.1", "localhost", "::1"}
        return left in loopback and right in loopback

    @app.middleware("http")
    async def guard(request, call_next):
        if request.url.path.startswith("/api/"):
            token = request.headers.get("Authorization", "").removeprefix("Bearer ") or request.query_params.get("token")
            if not authorized(token):
                return JSONResponse({"detail": "桌面会话已失效，请重新打开窗口"}, status_code=401)
            origin = request.headers.get("origin")
            if not same_origin(origin, request.base_url):
                return JSONResponse({"detail": "请求来源不匹配"}, status_code=403)
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; frame-src 'self'; connect-src 'self' ws://127.0.0.1:*; object-src 'none'; base-uri 'self'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({"detail": "文件暂不可用"}, status_code=404)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/bridge.js")
    def bridge():
        return Response(gateway.bridge_js or "window.yuanjingBridgeUnavailable = true;", media_type="application/javascript")

    @app.get("/brand.png")
    def brand():
        return FileResponse(Path(__file__).resolve().parent.parent / "desktop" / "assets" / "brand_app.png")

    @app.get("/mermaid.js")
    def mermaid():
        return FileResponse(Path(__file__).resolve().parent.parent / "desktop" / "assets" / "mermaid.min.js", media_type="application/javascript")

    @app.get("/api/bootstrap")
    def bootstrap():
        return gateway.bootstrap()

    @app.get("/api/conversations")
    def conversations():
        return gateway.recent()

    @app.get("/api/conversations/{cid}")
    def conversation(cid: int):
        return gateway.service.conversation(cid)

    @app.patch("/api/conversations/{cid}")
    async def rename(cid: int, request: Request):
        body = await request.json()
        title = str(body.get("title", "")).strip()
        if not title:
            raise ValueError("请输入对话名称")
        with Database.open(paths.db_path) as db:
            Conversations(db).get(cid)
            db.execute("UPDATE conversations SET title=? WHERE id=?", (title[:80], cid))
        return gateway.service.conversation(cid)

    @app.get("/api/page/{view}")
    def page(view: str, search: str = "", page: int = 0, segment: str = "raw"):
        if view not in ("works", "users", "analyses", "tasks") or segment not in ("raw", "active", "repeated", "incomplete", "unsampled"):
            raise ValueError("未知数据视图")
        return gateway.service.page(view, search, page, segment)

    @app.get("/api/benchmarks")
    def benchmarks():
        return gateway.service.benchmarks()

    @app.post("/api/benchmarks")
    async def add_benchmark(request: Request):
        return gateway.service.add_benchmark((await request.json()).get("url", ""))

    @app.delete("/api/benchmarks/{uid}")
    def remove_benchmark(uid: str):
        gateway.service.remove_benchmark(uid)
        return {"ok": True}

    @app.get("/api/enterprise")
    def enterprise():
        return gateway.service.enterprise_workspace()

    @app.put("/api/enterprise")
    async def save_enterprise(request: Request):
        return gateway.service.save_enterprise(await request.json())

    @app.get("/api/reports/{report_id}")
    def report(report_id: int):
        from ..analyze.enterprise import render_output
        data = gateway.service.enterprise_report(report_id)
        data["rendered"] = render_output(data["output"])
        return data

    @app.post("/api/reports/{report_id}")
    async def revise(report_id: int, request: Request):
        body = await request.json()
        return gateway.service.revise_enterprise(report_id, body.get("content", ""), body.get("reason", ""), bool(body.get("reviewed")))

    @app.put("/api/metrics")
    async def metrics(request: Request):
        return gateway.service.save_enterprise_metrics(await request.json())

    @app.get("/api/settings")
    def settings():
        return gateway.service.settings()

    @app.put("/api/settings")
    async def save_settings(request: Request):
        if gateway.job and gateway.job.state == "running":
            raise ValueError("请在当前任务结束后保存模型设置")
        body = await request.json()
        return gateway.service.save_settings(str(body.get("api_key", "")), str(body.get("model", "")),
                                              body.get("reasoning_effort"))

    @app.put("/api/preferences")
    async def preferences(request: Request):
        return gateway.save_preferences(await request.json())

    @app.get("/api/hot")
    def hot():
        # 有 AI 评估过的最新看板就用它；否则退回本地快照（不联网）
        return gateway.last_hot or gateway.service.hot_snapshot()

    @app.get("/api/job")
    def job():
        return gateway.job.public() if gateway.job else None

    @app.post("/api/jobs")
    async def start(request: Request):
        body = await request.json()
        return await gateway.start(body.get("kind", "chat"), body.get("options", {}))

    @app.post("/api/jobs/stop")
    async def stop():
        return await gateway.cancel()

    @app.post("/api/jobs/steer")
    async def steer(request: Request):
        return await gateway.steer(str((await request.json()).get("text", "")))

    @app.post("/api/jobs/confirm")
    async def confirm(request: Request):
        body = await request.json()
        if not gateway.job:
            raise ValueError("当前没有等待确认的任务")
        return {"ok": gateway.job.broker.resolve(str(body.get("request_id")), body.get("approved") is True)}

    @app.put("/api/uploads")
    async def upload(request: Request, name: str):
        safe_name = Path(name.replace("\\", "/")).name
        if not safe_name or safe_name in (".", ".."):
            raise ValueError("文件名无效")
        directory = gateway.upload_root / secrets.token_hex(16)
        directory.mkdir()
        output = directory / safe_name
        try:
            with output.open("wb") as stream:
                async for chunk in request.stream():
                    await asyncio.to_thread(stream.write, chunk)
            return gateway.register([output], temporary=True)[0]
        except BaseException:
            output.unlink(missing_ok=True)
            directory.rmdir()
            raise

    @app.delete("/api/uploads/{identifier}")
    def discard_upload(identifier: str):
        gateway.discard(identifier)
        return {"ok": True}

    def inline_file(path, name, *, download=False):
        guessed = mimetypes.guess_type(name)[0] or "application/octet-stream"
        safe = guessed.startswith(("image/", "video/", "audio/")) and guessed != "image/svg+xml"
        mime = guessed if safe or guessed == "application/pdf" else "text/plain" if guessed.startswith("text/") else "application/octet-stream"
        return FileResponse(path, media_type=mime, filename=Path(name).name, content_disposition_type="attachment" if download else "inline")

    def thumbnail(path):
        from ..attachments import _image, _run_ffmpeg
        key = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}".encode()).hexdigest()
        target = paths.state_dir / "html-previews" / (key + ".jpg")
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            if path.suffix.lower() in VIDEOS:
                _run_ffmpeg(["-ss", "0", "-i", str(path), "-frames:v", "1", "-vf", "scale=640:480:force_original_aspect_ratio=decrease", "-y", str(target)])
                if not target.exists():
                    raise ValueError("暂不能生成视频封面")
            else:
                _image(path, target, edge=640)
        return FileResponse(target, media_type="image/jpeg")

    @app.get("/api/uploads/{identifier}/preview")
    def upload_preview(identifier: str):
        return thumbnail(gateway.upload(identifier).path)

    @app.get("/api/uploads/{identifier}/file")
    def upload_file(identifier: str):
        item = gateway.upload(identifier)
        return inline_file(item.path, item.path.name)

    @app.get("/api/library")
    def library(offset: int = 0, count: int = 60, query: str = ""):
        return gateway.library(max(0, offset), max(1, count), query)

    @app.get("/api/attachments/{identifier}/assets")
    def assets(identifier: str, offset: int = 0, count: int = 60, query: str = "", kind: str = ""):
        return gateway.assets(identifier, offset=max(0, offset), count=max(1, count), query=query, kind=kind)

    video_locks = {}

    @app.get("/api/files/{identifier}")
    async def file(identifier: str, asset_id: str | None = None, variant: str = "source", download: bool = False):
        path, name = await asyncio.to_thread(gateway.resolve_file, identifier, asset_id, variant)
        if variant == "thumbnail" and not asset_id:
            return await asyncio.to_thread(thumbnail, path)
        if variant == "web-video":
            from ..attachments import ffmpeg_exe
            key = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}".encode()).hexdigest()
            folder = paths.state_dir / "html-previews"
            folder.mkdir(exist_ok=True)
            target = folder / (key + ".webm")
            lock = video_locks.setdefault(key, asyncio.Lock())
            async with lock:
                if not target.exists():
                    temporary = folder / (key + ".pending.webm")
                    process = await asyncio.create_subprocess_exec(ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-protocol_whitelist", "file,pipe", "-i", str(path), "-vf", "scale=1280:720:force_original_aspect_ratio=decrease",
                        "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "6", "-crf", "34", "-b:v", "0", "-c:a", "libopus", "-y", str(temporary),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
                    try:
                        stdout, stderr = await process.communicate()
                        if process.returncode:
                            raise ValueError("兼容预览生成失败：" + stderr.decode("utf-8", "replace")[-600:])
                        temporary.replace(target)
                    except BaseException:
                        if process.returncode is None:
                            process.terminate()
                            await process.wait()
                        temporary.unlink(missing_ok=True)
                        raise
            return inline_file(target, Path(name).stem + ".webm")
        return inline_file(path, name, download=download)

    @app.get("/api/files/{identifier}/text")
    def text(identifier: str, asset_id: str | None = None, offset: int = 0, count: int = 16000):
        from ..attachment_documents import read_text_segment
        path, name = gateway.resolve_file(identifier, asset_id)
        content, more = read_text_segment(path, max(0, offset), max(1, count))
        return {"name": name, "text": content, "next_offset": offset + len(content), "has_more": more}

    @app.websocket("/api/events")
    async def events(socket: WebSocket):
        origin = socket.headers.get("origin")
        expected = "http://" + socket.headers.get("host", "")
        if not authorized(socket.query_params.get("token")) or not same_origin(origin, expected):
            await socket.close(code=1008)
            return
        await socket.accept()
        queue = asyncio.Queue(maxsize=256)
        gateway.subscribers.add(queue)
        try:
            await socket.send_json({"type": "snapshot", "job": gateway.job.public() if gateway.job else None})
            while True:
                # Receiving also detects a closed idle client, without waiting for a job.
                incoming = asyncio.create_task(socket.receive_text())
                outgoing = asyncio.create_task(queue.get())
                done, pending = await asyncio.wait((incoming, outgoing), return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if outgoing in done:
                    await socket.send_json(outgoing.result())
                if incoming in done:
                    incoming.result()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            gateway.subscribers.discard(queue)

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (dist / "index.html").is_file():
            return Response("请先在 desktop-html 目录运行 npm install 和 npm run build。", status_code=503)
        return FileResponse(dist / "index.html", media_type="text/html")

    return app
