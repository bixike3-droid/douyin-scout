"""Windows release entry; the Qt HTML and original Qt entries remain available."""
from pathlib import Path
import os
import sys


if __name__ == "__main__":
    try:
        from scout.web_desktop.edge import main
        root = None if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent / "desktop/userdata"
        raise SystemExit(main(default_root=root))
    except Exception:
        import traceback
        directory = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "douyin-scout"
        directory.mkdir(parents=True, exist_ok=True)
        log = directory / "startup.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32" and not any(flag in sys.argv for flag in ("--screenshot", "--self-check", "--serve-only")):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"启动没有完成，请查看：\n{log}", "源镜", 0x10)
        raise
