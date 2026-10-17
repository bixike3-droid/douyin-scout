"""评论采集（P2.3 阶段 2）：解析、按作品归口、抽样预算与幂等入库。"""
import asyncio
import json
from urllib.parse import parse_qs, urlparse

from scout.collect.comments import CommentsCollector
from scout.parse.registry import parse_payload


def install_browser(ctx, monkeypatch, responder):
    calls = []

    class Page:
        url = "https://www.douyin.com/"

    class Session:
        async def ensure(self, tier):
            pass

        async def page(self, tier):
            return Page()

    async def session(*args, **kwargs):
        return Session()

    async def wait(*args):
        return 0

    async def fetch(self, page, url):
        calls.append(url)
        payload, status = responder(parse_qs(urlparse(url).query), url)
        return json.dumps(payload).encode(), status, ""

    monkeypatch.setattr(ctx, "open_session", session)
    monkeypatch.setattr(ctx.throttle, "wait", wait)
    monkeypatch.setattr("scout.collect.api_base.ApiCollector.fetch_in_page", fetch)
    ctx.quota.set_limit("a", 0)
    return calls


def comment_pages(total, aweme_id="777"):
    def responder(query, url):
        offset = int(query["cursor"][0])
        size = int(query["count"][0])
        end = min(total, offset + size)
        items = [
            {
                "cid": f"c{index}",
                "text": f"评论 {index}",
                "aweme_id": aweme_id,
                "create_time": 1700000000 + index,
                "digg_count": index % 7,
                "reply_comment_total": index % 3,
                "user": {"sec_uid": f"u{index % 5}", "nickname": f"用户{index % 5}",
                         "follower_count": 0},
            }
            for index in range(offset, end)
        ]
        return {"status_code": 0, "comments": items, "cursor": end,
                "has_more": end < total}, 200
    return responder


def test_comment_parser_keeps_work_scope_and_cursor():
    url = "https://www.douyin.com/aweme/v1/web/comment/list/?aweme_id=777&cursor=0&count=20"
    payload = {"status_code": 0, "comments": [
        {"cid": "c1", "text": "第一条", "aweme_id": "777", "create_time": 1700000000,
         "digg_count": 5, "reply_comment_total": 2,
         "user": {"sec_uid": "u1", "nickname": "甲", "follower_count": 10}},
    ], "cursor": 20, "has_more": 1, "total": 41}
    result = parse_payload(url, payload)
    assert result.kind == "comments"
    assert len(result.comments) == 1
    comment = result.comments[0]
    assert comment["comment_id"] == "c1" and comment["aweme_id"] == "777"
    assert comment["sec_uid"] == "u1" and comment["text"] == "第一条"
    assert comment["digg_count"] == 5 and comment["reply_count"] == 2
    assert result.users[0]["nickname"] == "甲"
    assert result.cursor["has_more"] is True and result.cursor["cursor"] == 20


def test_comments_budget_follows_work_volume(ctx):
    ctx.works.upsert({"aweme_id": "big", "comment_count": 10000})
    ctx.works.upsert({"aweme_id": "small", "comment_count": 10})
    collector = CommentsCollector(ctx)
    assert collector.max_items({"target": "big"}) == 100      # 爆款 → 抽样封顶
    assert collector.max_items({"target": "small"}) == 10     # 小评论 → 全采
    assert collector.max_items({"target": "small", "_item_limit": 3}) == 3


def test_comments_collector_pages_budgets_and_dedupes(ctx, monkeypatch):
    ctx.works.upsert({"aweme_id": "777", "comment_count": 10000})
    calls = install_browser(ctx, monkeypatch, comment_pages(400))
    result = asyncio.run(CommentsCollector(ctx).run({"target": "777", "tier": "a"}))
    assert result.ok and result.persisted["collection_state"] == "sampled"
    assert len(calls) == 5                          # 预算 100 / 每页 20
    assert result.persisted["items"] == 100
    assert ctx.comments.count_for_work("777") == 100
    assert ctx.db.scalar("SELECT COUNT(*) FROM users") >= 5
    rows = ctx.comments.list_for_work("777", limit=3)
    assert rows and all(row["aweme_id"] == "777" for row in rows)
    again = asyncio.run(CommentsCollector(ctx).run({"target": "777", "tier": "a", "_resume": True}))
    assert again.ok and ctx.comments.count_for_work("777") == 100   # 幂等：不重复入库
