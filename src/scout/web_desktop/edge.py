"""Windows desktop carrier using the installed Microsoft WebView2 runtime."""
from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from urllib.parse import urlsplit
import webbrowser

from .server import Server


class DesktopBridge:
    """Only trusted desktop gestures can grant original local-file access."""

    def __init__(self, gateway, attached=()):
        self._gateway = gateway
        self._attached = list(attached)
        self._window = None

    def _authorize(self, token):
        if not isinstance(token, str) or not secrets.compare_digest(token, self._gateway.token):
            raise ValueError("桌面会话已失效")

    def initialFiles(self, token):
        self._authorize(token)
        files, self._attached = self._attached, []
        return json.dumps(self._gateway.register(files), ensure_ascii=False)

    def pickFiles(self, token):
        self._authorize(token)
        import webview
        files = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=("所有文件 (*.*)",))
        return json.dumps(self._gateway.register(files or ()), ensure_ascii=False)

    def openDataFolder(self, token):
        self._authorize(token)
        os.startfile(str(self._gateway.paths.data_dir))

    def windowAction(self, token, action):
        self._authorize(token)
        window = self._window
        if action == "close":
            window.destroy()
        elif action == "minimize":
            window.minimize()
        elif action == "maximize":
            window.restore() if window.native.WindowState.ToString() == "Maximized" else window.maximize()
        elif action == "drag" or action.startswith("resize:"):
            # 必须在 WinForms 的 UI 线程上发起：WebView2 子控件持有鼠标捕获，
            # 从桥接线程调用 ReleaseCapture 释放不了，窗口就不会跟着动。
            # 同时，鼠标落在子控件上时 WM_NCHITTEST 不会交给顶层窗体，
            # 所以移动/拉伸都由前端边条触发，这里统一转成 WM_NCLBUTTONDOWN。
            from System import Action
            user = ctypes.windll.user32
            hwnd = int(window.native.Handle.ToInt64())
            root = user.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
            hits = {"left": 10, "right": 11, "top": 12, "topleft": 13,
                    "topright": 14, "bottom": 15, "bottomleft": 16, "bottomright": 17}
            if action == "drag":
                code = 2  # HTCAPTION
            else:
                code = hits.get(action.split(":", 1)[1])
                if code is None:
                    raise ValueError(f"未知的缩放方向：{action}")

            def start_move():
                if action != "drag" and window.native.WindowState.ToString() == "Maximized":
                    return
                user.ReleaseCapture()
                posted = user.PostMessageW(ctypes.c_void_p(root), 0x00A1, code, 0)
                logging.info("%s root=%s posted=%s", action, root, bool(posted))

            window.native.Invoke(Action(start_move))


def trusted_navigation(url, *origins):
    value = urlsplit(url)
    return url == "about:blank" or (value.scheme == "http" and any(value.netloc == urlsplit(o).netloc for o in origins))


def main(default_root=None):
    parser = argparse.ArgumentParser(description="源镜桌面版")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=0, help="本地服务固定端口（0 = 随机）")
    parser.add_argument("--frontend", help="开发模式：窗口直接加载该地址（如 http://127.0.0.1:5173/），适合 Vite 热更新")
    parser.add_argument("--attach", nargs="*", type=Path, default=[])
    parser.add_argument("--serve-only", action="store_true")
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--debug-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--self-check", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.frontend and urlsplit(args.frontend).hostname not in ("127.0.0.1", "localhost"):
        parser.error("--frontend 只能指向本机回环地址")
    from ..desktop.runtime import prepare_runtime
    from .gateway import Gateway
    from .api import create_app
    paths = prepare_runtime(args.data_dir or default_root)
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=paths.log_dir / "html-desktop.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.self_check:
        from .selfcheck import check
        return check(paths, args.self_check)
    gateway = Gateway(paths)
    gateway.native = not args.serve_only
    server = Server(create_app(paths, gateway=gateway), port=args.port)
    server.start()
    origin = f"http://127.0.0.1:{server.port}"
    # 开发模式下页面来自 Vite，/api 由 Vite 代理回本地服务；两个源都允许导航
    frontend = (args.frontend or origin).rstrip("/")
    if args.ready_file:
        args.ready_file.parent.mkdir(parents=True, exist_ok=True)
        args.ready_file.write_text(json.dumps({"port": server.port, "token": gateway.token, "pid": os.getpid()}), encoding="utf-8")
    if args.serve_only:
        try:
            while server.thread.is_alive():
                time.sleep(.25)
        except KeyboardInterrupt:
            pass
        finally:
            server.close()
        return 0

    import webview
    from webview.dom import DOMEventHandler
    webview.settings.update(ALLOW_DOWNLOADS=True, ALLOW_FILE_URLS=False,
                            OPEN_EXTERNAL_LINKS_IN_BROWSER=True, OPEN_DEVTOOLS_IN_DEBUG=False,
                            SHOW_DEFAULT_MENUS=False, REMOTE_DEBUGGING_PORT=args.debug_port)
    bridge = DesktopBridge(gateway, args.attach)
    preferences_file = paths.state_dir / "window-webview2.json"
    try:
        geometry = json.loads(preferences_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        geometry = {}
    window = webview.create_window(
        "源镜", f"{frontend}/#token={gateway.token}&native=webview2", js_api=bridge,
        width=max(1040, min(geometry.get("width", 1440), 2400)),
        height=max(680, min(geometry.get("height", 960), 1800)), min_size=(1040, 680),
        frameless=True, easy_drag=False, shadow=True, background_color="#f7f7f5",
        text_select=True, zoomable=False,
    )
    bridge._window = window

    def dispatch(name, value):
        window.evaluate_js(f"window.dispatchEvent(new CustomEvent({json.dumps(name)}, {{detail:{json.dumps(value, ensure_ascii=False)}}}))")

    def on_drop(event):
        files = [f["pywebviewFullPath"] for f in event.get("dataTransfer", {}).get("files", []) if f.get("pywebviewFullPath")]
        logging.info("Native drop: %s entries, %s original paths", len(event.get("dataTransfer", {}).get("files", [])), len(files))
        if files:
            dispatch("yuanjing-files-dropped", json.dumps(gateway.register(files), ensure_ascii=False))
        dispatch("yuanjing-drag-state", False)

    def on_loaded():
        window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, False, debounce=300)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, False)
        window.evaluate_js("window.__YUANJING_DROP_READY__ = true")
        # Persist only window dimensions; never resurrect off-screen coordinates.
        if geometry.get("maximized"):
            window.maximize()
        if args.screenshot:
            def capture():
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if window.evaluate_js("!!document.querySelector('textarea') && document.querySelectorAll('header button').length === 3"):
                        break
                    time.sleep(.1)
                time.sleep(.5)
                from System import Action
                from System.IO import FileMode, FileStream
                from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                # WebView2 is GPU-composited: PrintWindow can return an empty
                # surface even while the native browser is rendering correctly.
                stream = FileStream(str(args.screenshot), FileMode.Create)
                pending = {}
                def begin_capture():
                    pending["task"] = window.native.webview.CoreWebView2.CapturePreviewAsync(
                        CoreWebView2CapturePreviewImageFormat.Png, stream)
                try:
                    window.native.Invoke(Action(begin_capture))
                    if not pending["task"].Wait(15000):
                        raise TimeoutError("窗口截图未完成")
                finally:
                    stream.Dispose()
                diagnostic = window.evaluate_js("({title:document.title,renderer:window.pywebview.platform,files:document.querySelectorAll('textarea').length,body:document.body.innerText.slice(-2000)})")
                args.screenshot.with_suffix(".json").write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                window.destroy()
            threading.Thread(target=capture, daemon=True).start()

    def before_show():
        # Prevent a navigation from taking the privileged JS bridge off-origin.
        # This is bound to the native control before the initial page is shown.
        from System import Action
        def install():
            from .chrome import NativeChrome
            window._chrome = NativeChrome(window)
            def navigation(sender, event):
                target = str(event.Uri)
                if not trusted_navigation(target, origin, frontend):
                    event.Cancel = True
                    if urlsplit(target).scheme in ("https", "http"):
                        webbrowser.open(target)
            window.native.webview.NavigationStarting += navigation
            window._navigation_handler = navigation
        window.native.Invoke(Action(install))

    def on_closing():
        try:
            preferences_file.write_text(json.dumps({"width": window.width, "height": window.height,
                "maximized": window.native.WindowState.ToString() == "Maximized"}), encoding="utf-8")
        except Exception:
            logging.exception("Could not persist window geometry")

    window.events.loaded += on_loaded
    window.events.before_show += before_show
    window.events.closing += on_closing
    icon = Path(__file__).resolve().parent.parent / "desktop/assets/yuanjing.ico"
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(paths.data_dir / "webview2"), icon=str(icon))
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
