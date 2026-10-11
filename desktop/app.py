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


def _data_root() -> Path:
    """用户数据放哪。

    **不能放在程序目录里**，原因有两个：
      1. 打包成 exe 后，程序目录可能在 Program Files 下，是只读的
      2. 用户的 API Key 和数据**绝不能**跟着程序一起分发

    策略：优先用 exe 旁边的目录（绿色软件风格，卸载就是删文件夹）；
    那里不可写就退回系统用户目录。
    """
    import tempfile

    beside = _here() / "userdata"
    try:
        beside.mkdir(parents=True, exist_ok=True)
        probe = beside / ".writable"
        probe.write_text("1", encoding="utf-8")
        probe.unlink()
        return beside
    except OSError:
        pass

    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(
        Path.home() / ".config"
    )
    fallback = Path(base) / "douyin-scout"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


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


def _init_data() -> bool:
    """确保数据库存在、表结构完整。

    **桌面版必须自己做这件事**，不能让用户去终端跑 `scout init` ——
    用户不知道什么是终端，看到「请先在终端运行 scout init」只会一脸懵。

    这里跑一次迁移（幂等，重复运行无副作用）。
    """
    try:
        from scout.app import AppContext

        ctx = AppContext.create(migrate_db=True)
        try:
            n = ctx.db.scalar(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'", default=0
            )
            print(f"  数据库就绪（{n} 张表）")
        finally:
            ctx.close()
        return True
    except Exception as exc:
        print(f"  ⚠ 数据库初始化失败：{type(exc).__name__}: {exc}")
        return False


def main() -> None:
    # 桌面版用 main 账号目录：一台机器一个用户，服务器那套多账号隔离在这里没意义
    os.environ.setdefault("SCOUT_ACCOUNT", "main")
    # **数据目录指向用户可写位置**，而不是程序目录 ——
    # 否则打包后写不进去，而且用户的 Key 会跟程序一起被分发
    root = _data_root()
    os.environ["SCOUT_ROOT"] = str(root)
    os.environ["SCOUT_DATA_DIR"] = str(root / "data")

    print("=" * 58)
    print("  douyin-scout")
    print("=" * 58)
    print(f"  数据目录：{root}")
    print()

    print("  正在初始化…")
    _init_data()

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
