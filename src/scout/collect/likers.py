"""采集器：某作品的完整点赞人名单。

    GET /aweme/v1/web/favorite/list/?item_id=<视频ID>&count=50&max_cursor=0

实测（2026-10-10）：
- 单页上限 **50 人**，count 超过 50 会被接口拒绝（status_code=5）
- 但**分页是通的**：用上一页的 max_cursor 翻下一页，has_more 变 false 就到底
  （实测把 count 压到 5，靠 6 页把 27 人一个不少地凑齐）
- 每人带**完整主页数据**：昵称、签名、头像、粉丝数、关注数、作品数、获赞数、
  地区、认证、unique_id（抖音号）、sec_uid
- **不需要 a_bogus 签名**
- 必须登录态（匿名返回 status_code=8「用户未登录」）

所以"全部点赞人 + 每人主页"是一次接口调用就能拿全的，不用逐个访问主页。
"""

from __future__ import annotations

from typing import Any

from ..parse.registry import ParseResult
from ..util import iso
from .api_base import COMMON_PARAMS, ApiCollector

API_BASE = "https://www.douyin.com/aweme/v1/web/favorite/list/?"


class LikersCollector(ApiCollector):
    kind = "fetch_likers"

    @property
    def max_pages(self) -> int:
        return max(1, int(self.ctx.config.targets.likers_max_pages))

    def _page_size(self) -> int:
        # 接口硬上限 50，配置写大了会被拒
        return max(1, min(50, int(self.ctx.config.targets.likers_page_size)))

    def api_url(self, target: str, cursor: int) -> str:
        return (
            API_BASE
            + COMMON_PARAMS
            + f"&item_id={target}"
            + f"&count={self._page_size()}"
            + "&" + self.cursor_query(cursor)
        )

    def cursor_query(self, cursor: int) -> str:
        """点赞人接口用 min=max 也能翻（实测翻 6 页正常）。

        但这里仍然用基类默认的"只给 max_cursor" —— 实测这个写法对两个接口都有效，
        没必要为它保留一个特例。
        """
        return super().cursor_query(cursor)

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        raw_id = parsed.raw_blob_id
        saved = 0
        for user in parsed.users:
            if user.get("sec_uid"):
                ctx.users.upsert(user, raw_blob_id=raw_id)
                ctx.snapshots.record(user["sec_uid"], user)
                saved += 1

        added = ctx.like_edges.add_many(parsed.like_edges, tier=task.get("tier") or "a", raw_blob_id=raw_id)

        # **这次拿到的是完整名单，所以名单里的人都被"再次确认"了。**
        # 更新 last_confirmed_at，陈旧判断靠它。
        # 没在这次名单里的人不会被更新 —— 时间久了就说明对方可能取消了点赞。
        now = iso()
        for edge in parsed.like_edges:
            sec_uid = edge.get("sec_uid")
            aweme_id = edge.get("aweme_id")
            if sec_uid and aweme_id:
                ctx.db.execute(
                    "UPDATE like_edges SET last_confirmed_at = ?, is_stale = 0 "
                    "WHERE sec_uid = ? AND aweme_id = ?",
                    (now, sec_uid, aweme_id),
                )

        # 接口已经给了完整资料，这些人不用再跑主页采集
        for user in parsed.users:
            sec_uid = user.get("sec_uid")
            if sec_uid and user.get("follower_count") is not None:
                ctx.users.mark_state(sec_uid, "ok", tier=task.get("tier") or "a")

        return {"users_saved": saved, "new_edges": added, "confirmed": len(parsed.like_edges)}
