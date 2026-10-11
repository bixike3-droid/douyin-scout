"""douyin-scout 本地助手。

**为什么需要它**

抖音的登录凭据（sessionid / sid_tt / odin_tt 等）**全部是 HttpOnly 的** ——
网页 JS 读不到，所以"在网页上点一下就拿到 cookie"这条路被浏览器的安全模型堵死了。

而如果让服务器去登录，又会撞上抖音的验证码墙（实测：无头 / 有头 / 改 UA
访问 douyin.com 一律返回「验证码中间页」）。

**所以正确的位置是：用户自己的电脑。**

    用户在网页点「登录我的抖音」
      → 网页访问 http://127.0.0.1:18923/login
      → 本助手启动浏览器（用户自己电脑上，真实环境）
      → 用户扫码
      → 助手用 Playwright 从浏览器内部导出 storage_state
        （**这条路能拿到 HttpOnly cookie**，因为不是靠 JS 读的）
      → 助手直接上传到服务器（cookie 不经过网页 JS）
      → 网页显示"已连接"

**三条安全设计**

1. **CORS 白名单。** 只允许我们自己的域名调用。
   如果放开成 `*`，任何网站都能调用这个助手偷走用户的抖音 cookie。

2. **cookie 只走助手 → 服务器，不经过网页。**
   网页拿到的只是一个"成功/失败"。

3. **本地只监听 127.0.0.1**，外网访问不到。

**用户要做什么**：下载 → 双击 → 网页上点一下。不用装 Python，不用懂技术。
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import request as urlrequest

VERSION = "0.1.0"
PORT = int(os.environ.get("SCOUT_AGENT_PORT", "18923"))
HOST = "127.0.0.1"

# 允许调用本助手的来源。**必须是白名单** ——
# 放开成 * 等于让任何网站都能偷走用户的抖音登录态。
ALLOWED_ORIGINS = {
    "http://douyin.baodaoxiaoyuan.cn",
    "https://douyin.baodaoxiaoyuan.cn",
    "http://localhost",
    "http://127.0.0.1",
}

# 登录会话状态（全局，因为 HTTP handler 和 asyncio 线程要共享）
_state: dict[str, Any] = {
    "status": "idle",        # idle|starting|waiting|ok|error
    "message": "",
    "nickname": "",
    "sec_uid": "",
    "started_at": 0.0,
    "error": "",
}
_state_lock = threading.Lock()


def _set(**kw: Any) -> None:
    with _state_lock:
        _state.update(kw)


def _get() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def log(*a: Any) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


# ── 浏览器登录 ───────────────────────────────────────────────


async def _is_logged_in(ctx: Any) -> bool:
    """判断是否已登录。

    **直接看浏览器里的 cookie**，而不是看网页上的文字 ——
    因为 HttpOnly 的 cookie 只在浏览器内部可见，
    而 Playwright 的 `ctx.cookies()` 正是从内部读的。
    """
    try:
        cookies = await ctx.cookies()
    except Exception:
        return False
    names = {c.get("name") for c in cookies}
    return "sessionid" in names or "sessionid_ss" in names


async def _get_self(page: Any) -> tuple[str, str]:
    """登录后问一次"我是谁"，用来确认登录态真的可用。"""
    js = """
    async () => {
      try {
        const r = await fetch('/aweme/v1/web/user/profile/self/?device_platform=webapp&aid=6383',
                              {credentials: 'include'});
        const t = await r.text();
        const d = JSON.parse(t);
        const u = d.user || {};
        return {sec_uid: u.sec_uid || '', nickname: u.nickname || ''};
      } catch (e) { return {sec_uid: '', nickname: ''}; }
    }
    """
    try:
        r = await page.evaluate(js)
        return r.get("sec_uid", ""), r.get("nickname", "")
    except Exception:
        return "", ""


async def do_login(server_url: str, user_id: str, timeout_s: int = 300) -> None:
    """完整登录流程。跑在独立线程里，状态写进全局 _state。"""
    from playwright.async_api import async_playwright

    _set(status="starting", message="正在启动浏览器…", error="",
         started_at=time.time(), nickname="", sec_uid="")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,          # **必须有头** —— 用户要看着扫码
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                locale="zh-CN",
                viewport={"width": 1280, "height": 860},
            )
            page = await ctx.new_page()

            _set(status="waiting", message="正在打开抖音，请稍候…")
            await page.goto("https://www.douyin.com", wait_until="domcontentloaded",
                            timeout=45000)
            await asyncio.sleep(3)

            title = await page.title()
            if "验证码" in title:
                # 用户自己的环境下偶尔也会碰到，提示他手动过一下
                _set(status="waiting",
                     message="抖音要求人机验证 —— 请在打开的浏览器窗口里手动完成（拖一下滑块）")

            _set(status="waiting", message="请在打开的浏览器里扫码登录抖音")

            deadline = time.time() + timeout_s
            last_note = 0.0
            while time.time() < deadline:
                if await _is_logged_in(ctx):
                    break
                # 提示用户浏览器已经弹出来了，别以为卡住
                if time.time() - last_note > 20:
                    last_note = time.time()
                    _set(message="等待扫码中…（浏览器窗口应该已经弹出来了）")
                await asyncio.sleep(2)
            else:
                _set(status="error", error="超时未登录（5 分钟）",
                     message="没有检测到登录。请重新点一次登录。")
                await browser.close()
                return

            # 登录成功 —— 问一下是谁
            sec_uid, nickname = await _get_self(page)
            log(f"登录成功: {nickname or '(未知)'}")

            # **关键**：从浏览器内部导出，包含 HttpOnly cookie
            state = await ctx.storage_state()
            cookie_count = len(state.get("cookies") or [])
            log(f"导出登录态: {cookie_count} 个 cookie")

            _set(status="ok", message="登录成功，正在上传…",
                 nickname=nickname, sec_uid=sec_uid)

            ok, msg = _upload(server_url, user_id, state, nickname, sec_uid)
            if ok:
                _set(message=f"已连接：{nickname or '你的抖音账号'}")
                log("已上传到服务器")
            else:
                _set(status="error", error=msg,
                     message=f"登录成功，但上传失败：{msg}")
            await browser.close()

    except Exception as exc:
        log(f"登录出错: {type(exc).__name__}: {exc}")
        _set(status="error", error=f"{type(exc).__name__}: {exc}",
             message="登录过程出错，看本助手窗口里的日志。")


def _upload(server_url: str, user_id: str, state: dict, nickname: str,
            sec_uid: str) -> tuple[bool, str]:
    """把登录态直接发给服务器。**不经过网页 JS。**"""
    if not server_url:
        return False, "没有指定服务器地址"
    url = server_url.rstrip("/") + "/api/agent/cookie"
    payload = json.dumps({
        "user_id": user_id,
        "storage_state": state,
        "nickname": nickname,
        "sec_uid": sec_uid,
    }, ensure_ascii=False).encode("utf-8")

    req = urlrequest.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlrequest.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            log(f"上传响应: HTTP {resp.status} {body[:200]}")
            return resp.status == 200, body[:200]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ── HTTP 服务 ────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = f"scout-agent/{VERSION}"

    def log_message(self, fmt: str, *args: Any) -> None:  # 静音默认日志
        pass

    # ── CORS ──

    def _origin_ok(self) -> str:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            return origin
        # 允许本地页面（方便开发调试）
        if origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"):
            return origin
        return ""

    def _send(self, code: int, obj: Any, *, cors: bool = True) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cors:
            origin = self._origin_ok()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        origin = self._origin_ok()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/ping":
            self._send(200, {"ok": True, "version": VERSION, "name": "douyin-scout 本地助手"})
        elif path == "/status":
            self._send(200, _get())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            data = {}

        if path == "/login":
            if _get()["status"] in ("starting", "waiting"):
                self._send(409, {"ok": False, "reason": "已经有一个登录在进行中"})
                return
            server_url = data.get("server_url") or ""
            user_id = data.get("user_id") or secrets.token_hex(16)
            threading.Thread(
                target=lambda: asyncio.run(do_login(server_url, user_id)),
                daemon=True,
            ).start()
            self._send(200, {"ok": True, "message": "已开始登录，请看弹出的浏览器窗口"})
        elif path == "/reset":
            _set(status="idle", message="", error="", nickname="", sec_uid="")
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})


def main() -> None:
    print("=" * 62)
    print("  douyin-scout 本地助手")
    print("=" * 62)
    print()
    print(f"  正在监听 http://{HOST}:{PORT}")
    print("  保持这个窗口开着，然后回到网页上点「登录我的抖音」。")
    print("  关掉这个窗口 = 断开连接。")
    print()

    try:
        httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        print(f"  ✗ 端口 {PORT} 被占用了：{exc}")
        print(f"    可能有另一个助手在跑。先关掉它，或者设环境变量换端口：")
        print(f"    set SCOUT_AGENT_PORT=18924")
        input("\n  按回车退出…")
        sys.exit(1)

    print("  ✓ 就绪。回到网页上操作吧。")
    print()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
        httpd.server_close()


if __name__ == "__main__":
    main()
