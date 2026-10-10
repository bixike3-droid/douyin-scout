"""采集器：我自己的账号资料。

    GET /aweme/v1/web/user/profile/self/

用途只有一个：**搞清楚"我是谁"（我自己的 sec_uid）**。

为什么非要它：整个采集链路必须区分两类作品 ——
「我的作品」（要采点赞人）和「点赞人的作品」（要采回来做画像）。
分不清就会变成"点赞人的点赞人"，无限套娃。

之前试过用"从通知流发现的作品就是我的"这个启发式判据，不可靠 ——
点赞边被清理过之后判据就失效了。直接问服务器"我是谁"才是稳的。
"""

from __future__ import annotations

from typing import Any

from ..parse.registry import ParseResult
from .api_base import COMMON_PARAMS, ApiCollector

API_URL = "https://www.douyin.com/aweme/v1/web/user/profile/self/?" + COMMON_PARAMS


class SelfCollector(ApiCollector):
    kind = "fetch_self"

    @property
    def max_pages(self) -> int:
        return 1

    def api_url(self, target: str, cursor: int) -> str:
        return API_URL

    def should_continue(self, parsed: ParseResult, cursor: int) -> int | None:
        return None          # 单页接口，没有分页

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        me = next((u for u in parsed.users if u.get("sec_uid")), None)
        if not me:
            return {}
        ctx.cursors.set("self_sec_uid", me["sec_uid"])
        ctx.users.upsert(me, raw_blob_id=parsed.raw_blob_id)
        marked = ctx.works.mark_mine_by_author(me["sec_uid"])
        ctx.db.log_event(
            "info", "self",
            f"识别到本人账号 {me.get('nickname')}（{me['sec_uid'][:20]}…），"
            f"标记了 {marked} 个我的作品",
        )
        return {"self_sec_uid": me["sec_uid"], "marked_mine": marked}
