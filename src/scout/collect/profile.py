"""档 B：用户资料。

匿名访问 `https://www.douyin.com/user/<sec_uid>`，让页面自己去请求资料接口，
我们从响应镜像里取。不做任何签名工作。
"""

from __future__ import annotations

from typing import Any

from ..humanize import human_gap, micro_move, scroll_steps
from ..parse.registry import ParseResult
from .base import Collector


class ProfileCollector(Collector):
    kind = "fetch_profile"
    default_tier = "b"

    def __init__(self, ctx):
        super().__init__(ctx)

    def url_for(self, target: str) -> str:
        if target.startswith("http"):
            return target
        return self.ctx.config.targets.user_url(target)

    async def interact(self, page: Any, session: Any) -> None:
        await micro_move(page)
        # 主页资料通常首屏就返回；轻滚一下足够触发，不要过度请求
        await scroll_steps(page, total_px=380, steps=4)
        await human_gap(0.5, 1.3)

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        sec_uid = task.get("target", "")
        raw_id = parsed.raw_blob_id
        saved = 0

        for user in parsed.users:
            target_uid = user.get("sec_uid") or sec_uid
            if not target_uid:
                continue
            # 只接受和任务目标一致、或带完整指标的记录，避免把推荐位用户写进主表
            if target_uid != sec_uid:
                continue
            user["profile_state"] = "ok"
            user["profile_tier"] = "b"
            ctx.users.upsert(user, raw_blob_id=raw_id)
            ctx.snapshots.record(target_uid, user)
            saved += 1

        if saved == 0:
            ctx.users.mark_state(sec_uid, "blocked", tier="b", error="页面未返回该用户资料")
        else:
            ctx.users.mark_state(sec_uid, "ok", tier="b")

        # 顺着建作品列表任务
        ctx.tasks.enqueue("fetch_user_works", sec_uid, "b", priority=80)

        return {"users_saved": saved, "works_task_queued": bool(saved)}
