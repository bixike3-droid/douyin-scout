"""补取单条作品详情（播放地址按需刷新）。

抖音的播放地址带 `x-expires`，存下来一两天就会失效。播放前如果发现过期，
就用真实浏览器在页面里请求一次详情接口，拿新的地址并写回 `works`。

只发一个请求，走同一套护栏（配额 / 熔断 / 节流）与归档，解析失败也能回放。
"""

from __future__ import annotations

import json
from typing import Any

from ..parse.registry import parse_payload
from ..work_media import UpstreamUnavailable, WorkMediaError
from .api_base import COMMON_PARAMS
from .base import Collector

DETAIL_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/?"


class _Fetcher(Collector):
    """只为拿到 `fetch_in_page`；不做导航，也不需要匹配选择器。"""

    kind = "refresh_work"

    def url_for(self, target: str) -> str:
        return target


async def fetch_work(ctx, aweme_id: str) -> dict[str, Any]:
    """刷新并返回作品记录；失败抛 WorkMediaError 的子类。"""
    tiers = [name for name in ("a", "b") if ctx.config.tier(name).enabled]
    if not tiers:
        raise UpstreamUnavailable("没有可用的采集档位")
    session = await ctx.open_session()
    fetcher = _Fetcher(ctx)
    page = await session.page(tiers[0])
    last_error = ""
    for tier in tiers:
        if "douyin.com" not in (page.url or ""):
            page = await session.goto(tier, ctx.config.targets.home_url,
                                      settle_s=ctx.tier_cfg(tier).page_stay_s)
        ctx.guard(tier)
        await ctx.throttle.wait(tier, ctx.tier_cfg(tier))
        ctx.throttle.note_request(tier)
        url = f"{DETAIL_API}aweme_id={aweme_id}&{COMMON_PARAMS}"
        try:
            body, status, err = await fetcher.fetch_in_page(page, url)
        finally:
            ctx.quota.consume(tier)
        if status != 200 or err:
            last_error = f"详情接口返回 HTTP {status}" if not err else err
            continue
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeError):
            last_error = "详情接口返回的不是 JSON"
            continue
        if payload.get("status_code") not in (0, None):
            last_error = f"详情接口拒绝访问（{payload.get('status_code')} {payload.get('status_msg') or ''}）".strip()
            continue
        ref = ctx.archive.save(body, url=url, tier=tier, content_type="application/json",
                               source="media", note=f"refresh_work:{aweme_id}")
        parsed = parse_payload(url, payload, raw_blob_id=ref.id)
        work = next((item for item in parsed.works
                     if str(item.get("aweme_id") or "") == str(aweme_id)), None)
        if not work or not work.get("play_url"):
            last_error = "详情里没有播放地址"
            continue
        ctx.works.upsert(work, raw_blob_id=ref.id)
        return work
    raise UpstreamUnavailable(last_error or "刷新播放地址失败")


__all__ = ["fetch_work", "WorkMediaError"]
