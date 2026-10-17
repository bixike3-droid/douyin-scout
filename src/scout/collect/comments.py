"""采集器：某作品的评论区（P2.3 阶段 2）。

接口（第一版按公开 web 结构实现，真实登录账号待核验）：

    GET /aweme/v1/web/comment/list/?aweme_id=<作品ID>&cursor=0&count=20

- 翻页用 cursor（偏移语义）+ has_more；与点赞人接口一样需要登录态。
- 采集预算按作品评论量走 collect/sampling.py：小评论全采、爆款抽样封顶。
- 归口约定：每条评论都带 aweme_id，后续界面/分析一律按作品查询。
"""
from __future__ import annotations

from typing import Any

from ..parse.registry import ParseResult
from .api_base import COMMON_PARAMS, ApiCollector
from .sampling import budget_for

API_BASE = "https://www.douyin.com/aweme/v1/web/comment/list/?"


class CommentsCollector(ApiCollector):
    kind = "fetch_comments"

    @property
    def max_pages(self) -> int:
        return max(1, int(self.ctx.config.targets.comments_max_pages))

    def _page_size(self) -> int:
        return max(1, min(50, int(self.ctx.config.targets.comments_page_size)))

    def max_items(self, task: dict[str, Any]) -> int:
        """按作品评论量给预算（collect/sampling.py）；显式 `_item_limit` 优先。"""
        explicit = int(task.get("_item_limit") or 0)
        if explicit:
            return explicit
        work = self.ctx.works.get(str(task.get("target") or "")) or {}
        return max(1, budget_for(self.ctx.config.targets, work.get("comment_count")))

    def api_url(self, target: str, cursor: int) -> str:
        return (
            API_BASE
            + COMMON_PARAMS
            + f"&aweme_id={target}"
            + f"&cursor={cursor}"
            + f"&count={self._page_size()}"
        )

    def _identifiers(self, parsed: ParseResult):
        if self.kind == "fetch_comments":
            return {str(c["comment_id"]) for c in parsed.comments if c.get("comment_id")}
        return super()._identifiers(parsed)

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        raw_id = parsed.raw_blob_id
        saved_users = 0
        for user in parsed.users:
            if user.get("sec_uid"):
                ctx.users.upsert(user, raw_blob_id=raw_id)
                ctx.snapshots.record(user["sec_uid"], user)
                saved_users += 1
        added = ctx.comments.upsert_many(parsed.comments, raw_blob_id=raw_id) if parsed.comments else 0
        return {"users": saved_users, "comments": added}
