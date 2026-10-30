"""热搜词条 → 代表视频与相关视频。

抖音没有公开的「话题视频列表」接口；实测可用的路径是：
    https://www.douyin.com/hot/<sentence_id>
会 302 到该热点的代表视频页（/video/<aweme_id>?modeFrom=hotDetail...），
页面自己加载详情与 20 条相关视频。这里只读页面已经拿到的响应，不另造请求。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from ..parse.registry import parse_payload
from ..store.hot import HotVideoLinks

VIDEO_PATH = re.compile(r"/video/(\d{6,32})")
SENTENCE_ID = re.compile(r"^\d{4,20}$")


async def fetch_hot_videos(ctx, sentence_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    sid = str(sentence_id or "").strip()
    if not SENTENCE_ID.match(sid):
        raise ValueError("话题编号不正确")
    tier = "b" if ctx.config.tier("b").enabled else "a"
    session = await ctx.open_session()
    context = (await session.ensure(tier)).context
    page = await context.new_page()
    captured: list[dict[str, Any]] = []
    seen: set[str] = set()

    async def on_response(response):
        try:
            if "json" not in (response.headers or {}).get("content-type", ""):
                return
            url = response.url
            if url in seen:
                return
            seen.add(url)
            body = await response.body()
            if len(body) > 4_000_000 or b"aweme_id" not in body:
                return
            payload = json.loads(body.decode("utf-8", errors="replace"))
            parsed = parse_payload(url, payload)
            if parsed.works:
                captured.append({"url": url, "body": body, "works": parsed.works})
        except Exception:
            return

    page.on("response", lambda response: asyncio.ensure_future(on_response(response)))
    final = ""
    representative = ""
    try:
        ctx.guard(tier)
        await page.goto(f"https://www.douyin.com/hot/{sid}", wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(4)
        try:
            await page.mouse.wheel(0, 900)
        except Exception:
            pass
        await asyncio.sleep(3)
        await asyncio.sleep(0.4)  # 让响应回调收尾
        final = page.url
        match = VIDEO_PATH.search(final)
        representative = match.group(1) if match else ""
    finally:
        ctx.quota.consume(tier)
        try:
            await page.close()
        except Exception:
            pass

    merged: dict[str, dict[str, Any]] = {}
    for entry in captured:
        for work in entry["works"]:
            aweme_id = str(work.get("aweme_id") or "")
            if not aweme_id:
                continue
            if aweme_id not in merged or (work.get("digg_count") or 0) > (merged[aweme_id].get("digg_count") or 0):
                merged[aweme_id] = work

    ordered: list[dict[str, Any]] = []
    if representative and representative in merged:
        ordered.append(merged.pop(representative))
    ordered.extend(sorted(merged.values(), key=lambda item: item.get("digg_count") or 0,
                          reverse=True)[: max(0, limit - len(ordered))])
    if not ordered:
        raise ValueError("没有从热点页拿到视频（页面结构可能变化，或需要登录）")

    for entry in captured:
        try:
            ctx.archive.save(entry["body"], url=entry["url"], tier=tier, content_type="application/json",
                             source="hot_video", note=f"hot:{sid}")
        except Exception:
            pass
    for work in ordered:
        ctx.works.upsert(work)
    HotVideoLinks(ctx.db).replace(sid, [work["aweme_id"] for work in ordered])
    return ordered
