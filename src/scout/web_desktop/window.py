"""Native Qt window hosting the HTML frontend and a private loopback service."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time


class Server:
    def __init__(self, app, port=0):
        import uvicorn
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", port))
        self.port = self.socket.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                                   access_log=False, log_config=None, log_level="warning", ws="websockets-sansio", timeout_graceful_shutdown=5))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("本地服务启动失败")
            time.sleep(.02)

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.socket.close()


def main(default_root=None):
    parser = argparse.ArgumentParser(description="源镜 HTML 桌面版")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--port", type=int, default=0, help="本地服务固定端口（0 = 随机）")
    parser.add_argument("--serve-only", action="store_true", help="仅启动本地界面服务，供浏览器验证")
    parser.add_argument("--ready-file", type=Path, help="将本地验证连接信息写入指定文件")
    parser.add_argument("--screenshot", type=Path, help="启动后保存窗口截图并退出")
    parser.add_argument("--attach", nargs="*", type=Path, default=[], help="在新窗口中添加本机文件")
    parser.add_argument("--frontend", help="开发模式：窗口直接加载该地址（如 http://127.0.0.1:5173/），适合 Vite 热更新")
    args = parser.parse_args()
    from ..desktop.runtime import prepare_runtime
    from .gateway import Gateway
    from .api import create_app
    paths = prepare_runtime(args.data_dir or default_root)
    logging.basicConfig(filename=paths.log_dir / "html-desktop.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    gateway = Gateway(paths)
    if args.serve_only:
        server = Server(create_app(paths, gateway=gateway), port=args.port)
        server.start()
        if args.ready_file:
            args.ready_file.parent.mkdir(parents=True, exist_ok=True)
            args.ready_file.write_text(json.dumps({"port": server.port, "token": gateway.token}), encoding="utf-8")
        try:
            while server.thread.is_alive():
                time.sleep(.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.close()
        return 0
    from PySide6.QtCore import Qt, QObject, Signal, Slot, QFile, QIODevice, QUrl, QTimer, QSettings, QEvent
    from PySide6.QtGui import QDesktopServices, QIcon, QShortcut, QKeySequence
    from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebChannel import QWebChannel
    app = QApplication(sys.argv[:1])
    app.setApplicationName("源镜 HTML")
    app.setOrganizationName("源镜")
    from ..desktop.i18n import install_chinese_ui
    install_chinese_ui(app)
    js = QFile(":/qtwebchannel/qwebchannel.js")
    if js.open(QIODevice.OpenModeFlag.ReadOnly):
        gateway.bridge_js = bytes(js.readAll()).decode("utf-8")
        js.close()
    gateway.native = True
    server = Server(create_app(paths, gateway=gateway), port=args.port)
    server.start()

    class Bridge(QObject):
        filesDropped = Signal(str)
        dragState = Signal(bool)

        @Slot(result=str)
        def initialFiles(self):
            files, args.attach = args.attach, []
            return json.dumps(gateway.register(files), ensure_ascii=False)

        @Slot(result=str)
        def pickFiles(self):
            files, _ = QFileDialog.getOpenFileNames(window, "添加文件", "", "所有文件 (*)")
            return json.dumps(gateway.register(files), ensure_ascii=False)

        @Slot(str)
        def windowAction(self, action):
            # 最小化/最大化必须交给系统（WM_SYSCOMMAND），否则 DWM 的过渡动画不会播放：
            # showMinimized()/showMaximized() 只是改窗口状态，窗口会「啪」地跳过去。
            def syscommand(code):
                import ctypes
                hwnd = int(window.winId())
                ok = bool(ctypes.windll.user32.PostMessageW(hwnd, 0x0112, code, 0))
                logging.info("windowAction %s -> WM_SYSCOMMAND 0x%X hwnd=%s posted=%s minimized=%s",
                             action, code, hwnd, ok, window.isMinimized())
                try:
                    probe = Path(__file__).resolve().parents[3] / "desktop-html" / "window-actions.log"
                    from datetime import datetime
                    with probe.open("a", encoding="utf-8") as handle:
                        handle.write(f"{datetime.now():%H:%M:%S} {action} hwnd={hwnd} posted={ok}\n")
                except OSError:
                    pass
                return ok

            is_windows = sys.platform == "win32"
            if action == "minimize":
                if not (is_windows and syscommand(0xF020)):       # SC_MINIMIZE
                    window.showMinimized()
            elif action == "maximize":
                code = 0xF120 if window.isMaximized() else 0xF030  # SC_RESTORE / SC_MAXIMIZE
                if not (is_windows and syscommand(code)):
                    window.showNormal() if window.isMaximized() else window.showMaximized()
            elif action == "close":
                window.close()
            elif action == "drag" and window.windowHandle():
                window.windowHandle().startSystemMove()

        @Slot()
        def openDataFolder(self):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir)))

    allowed_ports = {server.port}
    if args.frontend:
        from urllib.parse import urlsplit
        _dev_port = urlsplit(args.frontend).port
        if _dev_port:
            allowed_ports.add(_dev_port)

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            if url.scheme() in ("http", "https") and url.host() == "127.0.0.1" and url.port() in allowed_ports:
                return True
            if url.toString() == "about:blank":
                return True
            if kind == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ("https", "http"):
                QDesktopServices.openUrl(url)
            return False

        def createWindow(self, kind):
            # Route user-activated links through the same navigation policy.
            page = Page(profile, self)
            page.urlChanged.connect(lambda url: QDesktopServices.openUrl(url) if url.scheme() in ("https", "http") else None)
            return page

    class View(QWebEngineView):
        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
                bridge.dragState.emit(True)
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragMoveEvent(event)

        def dragLeaveEvent(self, event):
            bridge.dragState.emit(False)
            super().dragLeaveEvent(event)

        def dropEvent(self, event):
            local = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if local:
                bridge.filesDropped.emit(json.dumps(gateway.register(local), ensure_ascii=False))
                bridge.dragState.emit(False)
                event.acceptProposedAction()
            else:
                super().dropEvent(event)

    class Window(QMainWindow):
        # 抄 DSH：窗口保留原生框架（WS_CAPTION 在），只把客户区延伸到标题栏位置。
        # 这样 DWM 仍把窗口当“有标题栏的普通窗口”，最小化/最大化动画、Snap、
        # 任务栏缩略图全部是系统原生行为；我们只负责在客户区里画东西。
        TITLE_HEIGHT = 44
        BUTTON_WIDTH = 46
        RESIZE_EDGE = 6

        def __init__(self):
            super().__init__()
            self.setWindowTitle("源镜")
            self.setWindowFlags(Qt.WindowType.Window)
            self.resize(1440, 960)
            self.setMinimumSize(1040, 680)
            self.preferences = QSettings("源镜", "HTML窗口")
            saved = self.preferences.value("geometry")
            if saved:
                self.restoreGeometry(saved)
            self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent.parent / "desktop" / "assets" / "yuanjing.ico")))
            self.setCentralWidget(view)
            app.installEventFilter(self)

        def nativeEvent(self, event_type, message):
            if sys.platform != "win32":
                return super().nativeEvent(event_type, message)
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))

            # WM_NCCALCSIZE：把非客户区高度压成 0，客户区铺满整个窗口
            if msg.message == 0x0083 and msg.wParam:
                return True, 0

            # WM_NCHITTEST：告诉系统哪里是拖动区 / 缩放边，命中全靠系统，动画才不会丢
            if msg.message == 0x0084:
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(int(self.winId()), ctypes.byref(rect))
                scale = self.devicePixelRatioF() or 1.0
                point_x = ctypes.c_short(msg.lParam & 0xFFFF).value
                point_y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                x = (point_x - rect.left) / scale
                y = (point_y - rect.top) / scale
                width, height = self.width(), self.height()

                if not self.isMaximized():
                    edge = self.RESIZE_EDGE
                    left, right = x < edge, x > width - edge
                    top, bottom = y < edge, y > height - edge
                    if top and left: return True, 13      # HTTOPLEFT
                    if top and right: return True, 14     # HTTOPRIGHT
                    if bottom and left: return True, 16   # HTBOTTOMLEFT
                    if bottom and right: return True, 17  # HTBOTTOMRIGHT
                    if left: return True, 10              # HTLEFT
                    if right: return True, 11             # HTRIGHT
                    if top: return True, 12               # HTTOP
                    if bottom: return True, 15            # HTBOTTOM

                if y < self.TITLE_HEIGHT:
                    # 右侧三个按钮交给网页（HTCLIENT），其余标题区交给系统拖动（HTCAPTION）
                    if x >= width - self.BUTTON_WIDTH * 3:
                        return True, 1
                    return True, 2

                return True, 1

            return super().nativeEvent(event_type, message)

        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and not self.isMaximized() and hasattr(watched, "window") and watched.window() == self:
                position = self.mapFromGlobal(event.globalPosition().toPoint())
                x, y = position.x(), position.y()
                if 0 <= x < self.width() and 0 <= y < self.height():
                    edges = Qt.Edge(0)
                    if x < 6: edges |= Qt.Edge.LeftEdge
                    elif x > self.width() - 6: edges |= Qt.Edge.RightEdge
                    if y < 6: edges |= Qt.Edge.TopEdge
                    elif y > self.height() - 6: edges |= Qt.Edge.BottomEdge
                    if edges and self.windowHandle():
                        self.windowHandle().startSystemResize(edges)
                        return True
            return super().eventFilter(watched, event)

        def closeEvent(self, event):
            self.preferences.setValue("geometry", self.saveGeometry())
            # API shutdown cancels active work and awaits its existing cleanup.
            server.server.should_exit = True
            event.accept()

    profile = QWebEngineProfile("yuanjing-html", app)
    profile.setPersistentStoragePath(str(paths.data_dir / "webview"))
    profile.setCachePath(str(paths.data_dir / "webview-cache"))
    view = View()
    page = Page(profile, view)
    view.setPage(page)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
    channel = QWebChannel(page)
    bridge = Bridge(channel)
    channel.registerObject("desktop", bridge)
    page.setWebChannel(channel)
    window = Window()

    def save_download(request):
        filename, _ = QFileDialog.getSaveFileName(window, "保存文件", request.downloadFileName())
        if filename:
            request.setDownloadDirectory(str(Path(filename).parent))
            request.setDownloadFileName(Path(filename).name)
            request.accept()
        else:
            request.cancel()
    profile.downloadRequested.connect(save_download)
    frontend = (args.frontend or f"http://127.0.0.1:{server.port}").rstrip("/")
    def round_window_corners(window):
        """Win11 原生圆角（DWMWA_WINDOW_CORNER_PREFERENCE）。

        我们没有标题栏，DWM 默认不会给圆角；但又必须保留 WS_CAPTION 才能拿到
        最小化动画，所以圆角只能显式告诉 DWM。Win10 上调用会失败，忽略即可。
        """
        if sys.platform != "win32":
            return
        import ctypes
        try:
            hwnd = int(window.winId())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            value = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(value), ctypes.sizeof(value)
            )
        except (OSError, AttributeError):
            logging.info("round corners unsupported on this system")

    view.load(QUrl(f"{frontend}/#token={gateway.token}"))
    window.show()
    round_window_corners(window)
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            def save_diagnostic(value):
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        pass
                args.screenshot.with_suffix(".json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                window.grab().save(str(args.screenshot))
                window.close()
                app.quit()
            page.runJavaScript("JSON.stringify({title:document.title, qt:!!window.qt, channel:typeof window.QWebChannel==='function', stagedFiles:document.querySelectorAll('.composer-attachments .file-tile').length, windowControls:document.querySelectorAll('.window-controls button').length, body:document.body.innerText.slice(-1500)})", save_diagnostic)
        QTimer.singleShot(4500, window, capture)
    try:
        code = app.exec()
    finally:
        server.close()
    return code
