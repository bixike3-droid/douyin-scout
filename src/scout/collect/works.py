"""档 B：用户作品列表。

同一个主页地址，靠多滚几轮让页面加载更多作品。
落库时同时写两处：works（作品本体）和 user_work_listings（归属关系）。
"""

from __future__ import annotations

from typing import Any

from ..humanize import human_gap, human_scroll, micro_move
from ..parse.registry import ParseResult
from .base import Collector


class UserWorksCollector(Collector):
    kind = "fetch_user_works"
    default_tier = "b"

    def __init__(self, ctx):
        super().__init__(ctx)

    def url_for(self, target: str) -> str:
        if target.startswith("http"):
            return target
        return self.ctx.config.targets.user_url(target)

    async def interact(self, page: Any, session: Any) -> None:
        await micro_move(page)
        rounds = int(self.ctx.tier_cfg(self.default_tier).scroll_rounds)
        await human_scroll(page, rounds=rounds)
        await human_gap(0.6, 1.6)

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        sec_uid = task.get("target", "")
        raw_id = parsed.raw_blob_id

        for work in parsed.works:
            if not work.get("author_sec_uid"):
                work["author_sec_uid"] = sec_uid
            ctx.works.upsert(work, raw_blob_id=raw_id)

        ids = [w["aweme_id"] for w in parsed.works if w.get("aweme_id")]
        if ids:
            ctx.works.link_listings(sec_uid, ids, raw_blob_id=raw_id)

        # 作品里出现的作者（转发/合集）也建任务，但优先级低
        for user in parsed.users:
            other = user.get("sec_uid")
            if other and other != sec_uid:
                ctx.users.ensure(other, discovered_from=f"works:{sec_uid}")
                ctx.tasks.enqueue("fetch_profile", other, "b", priority=150)

        return {"works_saved": len(ids), "listings": len(ids)}
