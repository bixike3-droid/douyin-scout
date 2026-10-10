"""在 Web 进程里跑采集。

**为什么需要它**

原来网页是"只读观测台"，采集只能去终端敲 `scout run`。
对比赛作品来说这不合格 —— 用户在网页上就应该能干活。

**三条设计约束**（都是被实际条件逼出来的）

1. **全局单飞。** 一次只能跑一个采集。
   一个 Chromium 约 500MB，2GB 内存跑不了两个。
   第二个请求会被明确告知"正在采集，请等"，而不是把服务器搞 OOM。

2. **采集不受页面影响。** 跑在独立的 asyncio task 里。
   用户关掉浏览器，采集继续；回头再打开还能看到刚才的结果。

3. **进度广播用队列，不用回调。** 0 个订阅者和 3 个订阅者行为一致，
   晚来的人还能看到已经发生的事（靠 _history 回放）。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

# 历史事件保留多少条（供后连接的客户端回放）
HISTORY_LIMIT = 200


@dataclass
class RunState:
    running: bool = False
    run_id: str = ""
    kinds: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    ready: int = 0          # 本轮开始时有多少待办
    attempted: int = 0
    ok: int = 0
    empty: int = 0
    failed: int = 0
    blocked: int = 0
    stop_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["elapsed_s"] = round(
            (self.finished_at or time.time()) - self.started_at, 1
        ) if self.started_at else 0.0
        return d


class CollectionRunner:
    """全局唯一的采集执行器。"""

    _instance: "CollectionRunner | None" = None

    @classmethod
    def get(cls) -> "CollectionRunner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._history: list[dict] = []
        self.state = RunState()

    # ── 订阅 ────────────────────────────────────────────────

    def subscribe(self) -> tuple[asyncio.Queue, list[dict]]:
        """返回 (队列, 已发生的事件回放)。

        回放很重要：用户点开页面时采集可能已经跑了一半，
        不回放就只能看到后半段，会以为前面没跑。
        """
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q, list(self._history)

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _emit(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": time.time()}
        self._history.append(event)
        if len(self._history) > HISTORY_LIMIT:
            del self._history[: len(self._history) - HISTORY_LIMIT]
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass

    # ── 状态 ────────────────────────────────────────────────

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── 启动 ────────────────────────────────────────────────

    async def start(self, *, kinds: str = "", max_tasks: int = 0) -> dict[str, Any]:
        """启动一轮采集。已经在跑就拒绝（而不是排队 —— 排队会让人困惑）。"""
        if self.busy:
            return {
                "accepted": False,
                "reason": "正在采集，请等这一轮结束",
                "state": self.state.to_dict(),
            }

        self.state = RunState(
            running=True,
            run_id=uuid.uuid4().hex[:8],
            kinds=kinds,
            started_at=time.time(),
        )
        self._history.clear()
        self._task = asyncio.create_task(self._run(kinds=kinds, max_tasks=max_tasks))
        return {"accepted": True, "run_id": self.state.run_id, "state": self.state.to_dict()}

    async def stop(self) -> dict[str, Any]:
        """请求停止。采集中途停下是安全的 —— running 任务下次会被自动捞回。"""
        if not self.busy:
            return {"stopped": False, "reason": "没有在跑的采集"}
        assert self._task is not None
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self.state.running = False
        self.state.finished_at = time.time()
        self.state.stop_reason = "用户手动停止"
        self._emit({"type": "stopped"})
        return {"stopped": True}

    # ── 实际执行 ────────────────────────────────────────────

    async def _run(self, *, kinds: str, max_tasks: int) -> None:
        from ..app import AppContext
        from ..schedule import Engine

        ctx = None
        try:
            self._emit({"type": "phase", "phase": "seed", "text": "盘点待办任务…"})
            ctx = AppContext.create(migrate_db=True)
            engine = Engine(ctx)

            counts = engine.seed()
            self._emit({"type": "seeded", "counts": counts})

            stats = ctx.tasks.stats()
            self.state.ready = int(stats.get("ready", 0))
            self._emit({
                "type": "start",
                "ready": self.state.ready,
                "pending": int(stats.get("pending", 0)),
                "counts": counts,
            })

            if self.state.ready == 0:
                self._emit({
                    "type": "done", "attempted": 0, "ok": 0, "failed": 0,
                    "empty": 0, "blocked": 0,
                    "stop_reason": "没有待办任务（数据都是最新的）",
                })
                return

            def on_event(ev: dict[str, Any]) -> None:
                # 引擎推来的任务级事件：更新计数并转发
                if ev.get("type") == "task":
                    if ev.get("blocked"):
                        self.state.blocked += 1
                    elif ev.get("ok"):
                        self.state.ok += 1
                    elif ev.get("empty"):
                        self.state.empty += 1
                    else:
                        self.state.failed += 1
                    self.state.attempted = int(ev.get("attempted") or 0)
                self._emit(ev)

            want = [k.strip() for k in kinds.split(",") if k.strip()]
            report = await engine.run_round(
                max_tasks=max_tasks or None,
                kinds=want or None,
                on_event=on_event,
            )

            self.state.attempted = report.attempted
            self.state.ok = report.ok
            self.state.empty = report.empty
            self.state.failed = report.failed
            self.state.blocked = report.blocked
            self.state.stop_reason = report.stop_reason or "任务跑完"

            self._emit({
                "type": "done",
                "attempted": report.attempted,
                "ok": report.ok,
                "empty": report.empty,
                "failed": report.failed,
                "blocked": report.blocked,
                "stop_reason": self.state.stop_reason,
            })

        except asyncio.CancelledError:
            self.state.stop_reason = "用户手动停止"
            raise
        except Exception as exc:
            self.state.error = f"{type(exc).__name__}: {exc}"
            self._emit({"type": "error", "error": self.state.error})
        finally:
            if ctx is not None:
                try:
                    if ctx.session is not None:
                        await ctx.session.stop()
                except Exception:
                    pass
                try:
                    ctx.close()
                except Exception:
                    pass
            self.state.running = False
            self.state.finished_at = time.time()
            # 用 SSE 的客户端靠这个事件收尾（不然它们会一直挂着）
            self._emit({"type": "idle", "state": self.state.to_dict()})
