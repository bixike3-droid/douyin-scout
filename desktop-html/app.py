"""HTML desktop entry, independent from desktop/app.py."""
from pathlib import Path
if __name__ == "__main__":
    try:
        from scout.web_desktop.window import main
        raise SystemExit(main(default_root=Path(__file__).resolve().parent.parent / "desktop" / "userdata"))
    except Exception:
        import traceback
        import sys
        logfile = Path(__file__).resolve().parent / "startup.log"
        logfile.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动没有完成，请查看：\n{logfile}", "源镜", 0x10)
        raise
