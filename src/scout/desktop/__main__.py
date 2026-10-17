"""Run with python -m scout.desktop or desktop/app.py."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path


def install_crash_logging():
    """窗口模式没有控制台：把未捕获异常与 Qt 警告写进桌面日志，闪退时留下现场。"""
    def _qt_message(mode, context, message):
        value = getattr(mode, "value", mode)
        level = {0: logging.DEBUG, 1: logging.INFO, 2: logging.WARNING}.get(value, logging.ERROR)
        logging.getLogger("qt").log(level, "%s", message)

    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_message)
    except Exception:
        pass

    def _excepthook(exc_type, exc_value, traceback):
        logging.error("Unhandled exception", exc_info=(exc_type, exc_value, traceback))

    sys.excepthook = _excepthook
    threading.excepthook = lambda args: logging.error(
        "Unhandled thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def main(default_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="源镜原生桌面程序")
    parser.add_argument("--data-dir", type=Path, help="独立的用户数据根目录")
    parser.add_argument("--dev-mode", action="store_true", help="源码开发预览，安全状态下自动重载")
    args = parser.parse_args()
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as exc:
        error_root = args.data_dir or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "douyin-scout"
        error_root.mkdir(parents=True, exist_ok=True)
        error_file = error_root / "desktop-startup.log"
        error_file.write_text(str(exc), encoding="utf-8")
        message = f"桌面组件加载失败，请重新安装或重新下载程序。\n诊断文件：{error_file}"
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "启动失败", 0x10)
        elif sys.stderr is not None:
            print(message, file=sys.stderr)
        return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("源镜")
    app.setApplicationDisplayName("源镜")
    app.setOrganizationName("源镜")
    try:
        from PySide6.QtCore import QTimer
        from .runtime import prepare_runtime
        from .service import DesktopService
        from .splash import Splash
        from .window import MainWindow

        if getattr(sys, "frozen", False):
            default_root = Path(sys.executable).resolve().parent / "userdata"
        root = args.data_dir or default_root
        try:
            paths = prepare_runtime(root)
        except OSError:
            if args.data_dir is not None:
                raise
            paths = prepare_runtime()
        log_dir = paths.root / "logs"
        log_dir.mkdir(exist_ok=True)
        logging.basicConfig(filename=log_dir / "desktop.log", encoding="utf-8", level=logging.INFO)
        install_crash_logging()
        window = MainWindow(DesktopService(paths))
        if args.dev_mode and not getattr(sys, "frozen", False):
            from .dev import DevReload
            window.dev_reload = DevReload(window, Path(__file__).resolve().parents[3])
        # 启动页：真实阶段文案，最短 0.8s（避免一闪而过）、最长 6s（不让网络拖住）
        splash = Splash(motion=getattr(window, "motion_enabled", True))
        splash.show_centered()
        window.hide()
        started = time.monotonic()
        ticker = QTimer()

        def stage_text():
            if not window.initialized:
                return "正在读取本地数据"
            if not window.enterprise.hot_panel.loaded_once:
                return "正在同步抖音热榜"
            return "准备就绪"

        def tick():
            elapsed = time.monotonic() - started
            splash.set_stage(stage_text())
            if (window.initialized and elapsed >= 0.8) or elapsed >= 6.0:
                ticker.stop()
                window.show()
                window.raise_()
                splash.finish()

        ticker.timeout.connect(tick)
        ticker.start(120)
        return app.exec()
    except Exception as exc:
        logging.exception("Desktop startup failed")
        QMessageBox.critical(None, "启动失败", f"无法启动程序：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
