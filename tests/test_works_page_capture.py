"""作品采集：API 被 Argus 拦（403）时改读主页自身请求的兜底路径。"""
from __future__ import annotations

import asyncio

from scout.collect.user_works_api import UserWorksApiCollector

ME = "MS4wLjABAAAAme_aaaaaaaaaaaaaaaaaaaaaaaaaa"


def _work(aid: str, author: str = ME) -> dict:
    return {"aweme_id": aid, "desc": f"作品{aid}", "create_time": 1700000000,
            "author": {"sec_uid": author, "nickname": "本人"},
            "statistics": {"digg_count": 3, "comment_count": 1, "share_count": 0}}


class FakeResponse:
    def __init__(self, url, payload, status=200):
        self.url = url
        self.status = status
        self._payload = payload

    async def text(self):
        import json
        return json.dumps(self._payload, ensure_ascii=False)


class FakeMouse:
    def __init__(self, page):
        self.page = page

    async def wheel(self, x, y):
        self.page.on_wheel()


class FakePage:
    """模拟主页：第一次导航后页面自己发作品请求，滚动后再发一页。"""

    def __init__(self, pages, more_after_first=True):
        self.url = "https://www.douyin.com/"
        self.pages = pages
        self.more = more_after_first
        self.handlers = []
        self.emit_index = 0
        self.mouse = FakeMouse(self)

    def on(self, event, handler):
        if event == "response":
            self.handlers.append(handler)

    def remove_listener(self, event, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    async def fire(self, payload):
        # 真实场景里每页 URL 的 max_cursor 不同；这里也区分开，避免被去重逻辑当成重复响应
        cursor = payload.get("max_cursor") or 0
        response = FakeResponse(
            f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id={ME}&max_cursor={cursor}", payload)
        for handler in list(self.handlers):
            await handler(response)

    def on_wheel(self):
        if self.more and self.emit_index < len(self.pages):
            payload = self.pages[self.emit_index]
            self.emit_index += 1
            asyncio.get_event_loop().create_task(self.fire(payload))


class FakeSession:
    def __init__(self, page):
        self._page = page

    async def ensure(self, tier):
        return self

    async def page(self, tier):
        return self._page

    async def goto(self, tier, url, settle_s=1.0):
        self._page.url = url
        if self._page.pages:
            self._page.emit_index = 1
            await self._page.fire(self._page.pages[0])
        return self._page


def test_page_capture_fallback_persists_works(ctx, monkeypatch):
    ctx.cursors.set("self_sec_uid", ME)
    first = {"status_code": 0, "has_more": 1, "max_cursor": 111,
             "aweme_list": [_work("111"), _work("222")]}
    second = {"status_code": 0, "has_more": 0, "max_cursor": 0,
              "aweme_list": [_work("333")]}
    page = FakePage([first, second])
    monkeypatch.setattr(ctx, "open_session", lambda **kwargs: _coro(FakeSession(page)))

    async def fast_wait(bodies, before, timeout):
        for _ in range(3):
            await asyncio.sleep(0.01)

    monkeypatch.setattr(UserWorksApiCollector, "_wait_capture", staticmethod(fast_wait))

    collector = UserWorksApiCollector(ctx)
    outcome = asyncio.run(collector._run_by_page({"target": ME, "tier": "a"}))

    assert outcome.ok and outcome.error == ""
    assert outcome.persisted["mode"] == "page_capture"
    assert {w["aweme_id"] for w in ctx.works.list(mine_only=True, limit=10)} == {"111", "222", "333"}
    assert outcome.persisted["collection_state"] == "full"


def test_page_capture_empty_account_is_empty_not_error(ctx, monkeypatch):
    ctx.cursors.set("self_sec_uid", ME)
    page = FakePage([{"status_code": 0, "has_more": 0, "aweme_list": []}])
    monkeypatch.setattr(ctx, "open_session", lambda **kwargs: _coro(FakeSession(page)))

    async def fast_wait(bodies, before, timeout):
        for _ in range(2):
            await asyncio.sleep(0.01)

    monkeypatch.setattr(UserWorksApiCollector, "_wait_capture", staticmethod(fast_wait))
    outcome = asyncio.run(UserWorksApiCollector(ctx)._run_by_page({"target": ME, "tier": "a"}))
    assert outcome.ok and outcome.persisted["collection_state"] == "empty"


def _coro(value):
    async def inner():
        return value
    return inner()


