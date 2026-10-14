"""采集器：某个用户的作品列表。

    GET /aweme/v1/web/aweme/post/?sec_user_id=<sec_uid>&count=18&max_cursor=0

实测（2026-10-10）：不带签名直接 fetch 返回 200，每条作品带

    标题(desc)、时长(duration)、发布时间(create_time)、
    点赞/评论/转发/收藏数(statistics)、封面 URL、话题标签

**这就是 AI 做画像的原料** —— 没有它，AI 只能对着昵称和粉丝数瞎编。

和点赞人接口同一套路：页面内 fetch、分页翻到底、不需要签名、需要登录态。
"""

from __future__ import annotations

from typing import Any

from ..parse.registry import ParseResult
from .api_base import COMMON_PARAMS, ApiCollector

API_BASE = "https://www.douyin.com/aweme/v1/web/aweme/post/?"


class UserWorksApiCollector(ApiCollector):
    kind = "fetch_user_works"

    @property
    def max_pages(self) -> int:
        return max(1, int(self.ctx.config.targets.works_max_pages))

    def _page_size(self) -> int:
        size = max(1, min(50, int(self.ctx.config.targets.works_page_size)))
        remaining = getattr(self, "_remaining", 0)
        return min(size, remaining) if remaining else size

    def max_items(self, task):
        if task.get("target") == self.ctx.cursors.get("self_sec_uid"):
            return 0
        return max(0, int(task.get("_item_limit", self.ctx.config.targets.works_per_user_limit)))

    def filter_parsed(self, parsed, task):
        target = task.get("target")
        original = len(parsed.works)
        parsed.works = [w for w in parsed.works if w.get("author_sec_uid") == target]
        if len(parsed.works) != original:
            parsed.notes.append(f"跳过 {original-len(parsed.works)} 条作者归属未确认的作品")
        return parsed

    def api_url(self, target: str, cursor: int) -> str:
        return (
            API_BASE
            + COMMON_PARAMS
            + f"&sec_user_id={target}"
            + f"&count={self._page_size()}"
            + "&" + self.cursor_query(cursor)
            + "&locate_query=false&show_live_replay_strategy=1"
        )

    def persist(self, parsed: ParseResult, task: dict[str, Any]) -> dict[str, Any]:
        ctx = self.ctx
        sec_uid = task.get("target", "")
        raw_id = parsed.raw_blob_id

        # 第三层防护：**只关联作者确实是本人的作品**。
        # 前两层是"只读 aweme_list"和"解析时按作者过滤"，
        # 这一层兜住任何漏网的 —— 关联错了会让页面上出现
        # "98 粉丝的号挂着 178 万赞视频"这种一眼假的数据。
        linked: list[str] = []
        skipped = 0
        for work in parsed.works:
            aweme_id = work.get("aweme_id")
            if not aweme_id:
                continue
            author = work.get("author_sec_uid") or ""
            if sec_uid and author != sec_uid:
                skipped += 1
                continue
            ctx.works.upsert(work, raw_blob_id=raw_id)
            linked.append(aweme_id)

        if linked:
            ctx.works.link_listings(sec_uid, linked, raw_blob_id=raw_id)
            ctx.users.mark_state(sec_uid, "ok", tier="a")
            if sec_uid == ctx.cursors.get("self_sec_uid"):
                ctx.works.mark_mine_by_author(sec_uid)

        out = {"works_saved": len(linked), "works_linked": len(linked)}
        if skipped:
            out["skipped_other_author"] = skipped
        return out
