"""douyin-scout 桌面版。

**用户看到什么**

双击 exe（或 启动.bat）→ 弹出一个原生窗口 → 那就是整个程序。
没有浏览器、没有地址栏、没有标签页、没有命令行窗口。

**内部怎么做的**

进程里起一个只监听 127.0.0.1 的 uvicorn（随机端口），
再用 PyWebView 开一个原生窗口指向它。

为什么这么做而不是"用 Python API 直接桥接"：
- 现有的整个界面（约 1100 行）和 SSE 实时推送**一行都不用改**
- SSE 是长连接流式推送，改造成桥接调用要重写进度机制，风险大收益小
- 内嵌服务用户完全感知不到 —— 它不占端口冲突、不对外暴露

**这和"起个服务再打开浏览器"有本质区别**：
用户拿到的是一次双击、一个窗口。中间那层是实现细节，不是体验。
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path


def _here() -> Path:
    """程序所在目录。打包成 exe 后要用 exe 的位置，不能用 __file__。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _pick_port() -> int:
    """让系统分配一个空闲端口。写死端口会和别的软件撞。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _serve(port: int, ready: threading.Event) -> None:
    import uvicorn

    from scout.web.app import create_app

    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    ready.set()
    server.run()


def main() -> None:
    # 桌面版默认用 main 账号目录：这是用户自己机器上的唯一账号。
    # 服务器上那套多账号隔离（--account）在这里没有意义 ——
    # 一台机器一个用户。
    os.environ.setdefault("SCOUT_ACCOUNT", "main")

    print("=" * 58)
    print("  douyin-scout")
    print("=" * 58)
    print()

    try:
        import webview  # noqa: F401
    except ImportError:
        print("  缺少 pywebview。请先运行：")
        print("      pip install pywebview")
        print()
        input("  按回车退出…")
        sys.exit(1)

    port = _pick_port()
    ready = threading.Event()
    threading.Thread(target=_serve, args=(port, ready), daemon=True).start()

    print("  正在启动界面…")
    if not _wait_port(port):
        print("  启动失败：内部服务没能在 30 秒内就绪。")
        input("  按回车退出…")
        sys.exit(1)

    import webview

    window = webview.create_window(
        "douyin-scout",
        f"http://127.0.0.1:{port}/",
        width=1440,
        height=920,
        min_size=(1100, 700),
        text_select=True,
    )

    print(f"  界面已就绪（内部端口 {port}，仅本机可访问）")
    print("  关掉这个窗口 = 退出程序")
    print()

    # gui=None 让 pywebview 自己挑：Windows 上会用 WebView2（系统自带，不用打包浏览器）
    webview.start()

    print("  已退出。")


if __name__ == "__main__":
    main()
