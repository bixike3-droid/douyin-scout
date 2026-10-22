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
                if window._anim_group is not None:
                    return
                from PySide6.QtCore import QRect as _Rect
                start = window.geometry()
                screen = window.screen().availableGeometry()
                shrink = _Rect(
                    start.center().x() - start.width() // 6,
                    screen.bottom() - 90,
                    max(180, start.width() // 3),
                    max(120, start.height() // 3),
                )

                def done():
                    window._anim_minimized = True
                    window.showMinimized()
                    window.setWindowOpacity(1.0)
                    window.setGeometry(start)

                window.animate_to(shrink, 0.0, done, duration=160)
            elif action == "maximize":
                if window._anim_group is not None:
                    return
                from PySide6.QtCore import QRect as _Rect
                screen = window.screen().availableGeometry()
                if window.isMaximized():
                    start = window.geometry()
                    target = getattr(window, "_normal_geometry", None) or start.adjusted(40, 40, -40, -40)
                    window.setWindowState(Qt.WindowState.WindowNoState)
                    window.setGeometry(start)
                    window.animate_to(target, 1.0, lambda: None, duration=170)
                else:
                    window._normal_geometry = window.geometry()
                    window.animate_to(_Rect(screen), 1.0,
                                      lambda: window.setWindowState(Qt.WindowState.WindowMaximized),
                                      duration=170)
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
        def __init__(self):
            super().__init__()
            self.setWindowTitle("源镜")
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            self.resize(1440, 960)
            self.setMinimumSize(1040, 680)
            self._anim_group = None
            self._anim_minimized = False
            self.preferences = QSettings("源镜", "HTML窗口")
            saved = self.preferences.value("geometry")
            if saved:
                self.restoreGeometry(saved)
            self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent.parent / "desktop" / "assets" / "yuanjing.ico")))
            self.setCentralWidget(view)
            app.installEventFilter(self)

        # ---- 自绘最小化/还原动画（不依赖 DWM）----
        def animate_to(self, target, opacity, done, duration=170):
            from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation
            if self._anim_group is not None:
                return self._fallback(done)
            start = self.geometry()
            group = QParallelAnimationGroup(self)
            geo = QPropertyAnimation(self, b"geometry", group)
            geo.setDuration(duration)
            geo.setStartValue(start)
            geo.setEndValue(target)
            geo.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade = QPropertyAnimation(self, b"windowOpacity", group)
            fade.setDuration(duration)
            fade.setStartValue(self.windowOpacity())
            fade.setEndValue(opacity)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)

            def finished():
                self._anim_group = None
                self._anim_restore = start
                done()

            group.finished.connect(finished)
            self._anim_group = group
            group.start()

        def _fallback(self, done):
            done()

        def changeEvent(self, event):
            if event.type() == QEvent.Type.WindowStateChange and self._anim_minimized and not self.isMinimized():
                self._anim_minimized = False
                from PySide6.QtCore import QEasingCurve, QPropertyAnimation
                fade = QPropertyAnimation(self, b"windowOpacity", self)
                fade.setDuration(180)
                fade.setStartValue(0.0)
                fade.setEndValue(1.0)
                fade.setEasingCurve(QEasingCurve.Type.OutCubic)
                fade.start()
                self._anim_group = fade
                fade.finished.connect(lambda: setattr(self, "_anim_group", None))
            super().changeEvent(event)

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
    view.load(QUrl(f"{frontend}/#token={gateway.token}"))
    window.show()
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
