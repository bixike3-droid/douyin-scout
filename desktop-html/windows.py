"""Windows release entry; the Qt HTML and original Qt entries remain available."""
from pathlib import Path
import os
import sys


NETFX_MIN_RELEASE = 461808  # .NET Framework 4.7.2


def strip_zone_marks(root: Path) -> int:
    """去掉“来自网络”标记（Zone.Identifier）。

    用户从浏览器下载 zip 再解压时，每个文件都带这个标记；.NET 默认拒绝从
    网络位置加载程序集，表现就是 pythonnet / WebView2 初始化失败的崩溃。
    """
    if sys.platform != "win32" or not root.is_dir():
        return 0
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stream = f"{path}:Zone.Identifier"
        try:
            os.stat(stream)
        except OSError:
            continue
        try:
            os.remove(stream)
            removed += 1
        except OSError:
            pass
    return removed


def netfx_release() -> int:
    """已安装的 .NET Framework 4.x 版本号；读不到时返回 0（不阻断启动）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as key:
            return int(winreg.QueryValueEx(key, "Release")[0])
    except (OSError, ValueError):
        return 0


def _fatal(message: str) -> None:
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "douyin-scout"
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / "startup.log"
    log.write_text(message, encoding="utf-8")
    if sys.platform == "win32" and not any(flag in sys.argv for flag in ("--screenshot", "--self-check", "--serve-only")):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message[:1200], "源镜", 0x10)


if __name__ == "__main__":
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        strip_zone_marks(Path(sys.executable).parent)
        release = netfx_release()
        if release and release < NETFX_MIN_RELEASE:
            _fatal("启动需要 .NET Framework 4.7.2 或更高版本。\n"
                   f"当前检测到 Release={release}。请安装 .NET Framework 4.8 后重试：\n"
                   "https://dotnet.microsoft.com/download/dotnet-framework/net48")
            raise SystemExit(1)
    try:
        from scout.web_desktop.edge import main
        root = None if frozen else Path(__file__).resolve().parent.parent / "desktop/userdata"
        raise SystemExit(main(default_root=root))
    except SystemExit:
        raise
    except Exception:
        import traceback
        detail = traceback.format_exc()
        hint = ""
        if "pythonnet" in detail or "WebView2" in detail or "loadFromRemoteSources" in detail:
            hint = ("\n\n这通常是系统组件缺失或文件被“来自网络”标记阻断：\n"
                    "1) 右键安装包 → 属性 → 勾选「解除锁定」后重新解压；\n"
                    "2) 确认已安装 .NET Framework 4.8 与 Microsoft Edge WebView2 运行时。")
        _fatal("启动没有完成，请查看：\n" + str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "douyin-scout" / "startup.log")
              + hint + "\n\n" + detail[-1500:])
        raise SystemExit(1)

