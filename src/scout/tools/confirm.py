"""用户确认通道：需要确认的工具调用在这里挂起，等界面里的用户做出决定。

线程模型：对话循环跑在工作线程的 asyncio 事件循环里（await 等待），
Qt 主线程通过 resolve() 传入用户的选择（call_soon_threadsafe 回送结果）。
超时视为拒绝——安全默认。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from typing import Any, Callable

from .registry import ToolSpec

DEFAULT_TIMEOUT_S = 180.0
DETAIL_LIMIT = 200


class ConfirmationBroker:
    """一次「问用户」对应一个 request_id：界面拿到后调 resolve 作答。"""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.timeout_s = timeout_s
        self._waiters: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Future]] = {}
        self._lock = threading.Lock()
        self._counter = itertools.count(1)

    def new_id(self) -> str:
        return f"confirm-{int(time.time())}-{next(self._counter)}"

    async def ask(self, request_id: str) -> bool:
        """挂起直到用户作答；超时视为拒绝。应在运行对话的事件循环里 await。"""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        with self._lock:
            self._waiters[request_id] = (loop, future)
        try:
            return bool(await asyncio.wait_for(future, timeout=self.timeout_s))
        except asyncio.TimeoutError:
            return False
        finally:
            with self._lock:
                self._waiters.pop(request_id, None)

    def resolve(self, request_id: str, approved: bool) -> bool:
        """任意线程可调用（Qt 主线程点击按钮）；存在等待者返回 True。"""
        with self._lock:
            item = self._waiters.get(request_id)
        if item is None:
            return False
        loop, future = item

        def _deliver() -> None:
            if not future.done():
                future.set_result(bool(approved))

        try:
            loop.call_soon_threadsafe(_deliver)
        except RuntimeError:  # 事件循环已关闭
            return False
        return True

    def confirmer(self, emit: Callable[[dict], None]):
        """构造 registry.execute 需要的 confirm 回调：先抛事件给界面，再等用户选择。"""

        async def ask_user(spec: ToolSpec, agent_id: str, args: dict[str, Any]) -> bool:
            request_id = self.new_id()
            try:
                detail = json.dumps(args or {}, ensure_ascii=False)
            except (TypeError, ValueError):
                detail = str(args)
            if len(detail) > DETAIL_LIMIT:
                detail = detail[:DETAIL_LIMIT] + "…"
            emit({"type": "tool", "phase": "confirm", "request_id": request_id,
                  "tool": spec.id, "name": spec.name, "agent": agent_id, "detail": detail})
            approved = await self.ask(request_id)
            emit({"type": "tool", "phase": "confirm_done", "request_id": request_id,
                  "tool": spec.id, "approved": approved})
            return approved

        return ask_user
