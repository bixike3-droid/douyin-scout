"""热点工具：抖音实时热点榜。

与采集同一套合规路线：真实浏览器里由页面自身发起请求，程序只读响应。
失败（未开档位 / 触发验证 / 结构变化）都转成清晰的工具结果，不抛给对话。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .registry import ToolSpec, register
from ..collect.api_base import COMMON_PARAMS

# 实测（2026-10-15，匿名档 b）：该接口不需要签名，页面内 fetch 返回 50 条；
# 注意不能带 source=trending_page（接口要求 source 为整数，传字符串会 400）。
HOT_URL = ("https://www.douyin.com/aweme/v1/web/hot/search/list/?" + COMMON_PARAMS
           + "&detail_list=1")
# 走浏览器上下文直接请求时必须带 Referer，否则接口返回空体（2026-10-15 实测）。
HOT_HEADERS = {"Referer": "https://www.douyin.com/"}


async def _douyin_hot(ctx) -> dict:
    session = await ctx.open_session()
    page = await session.goto("b", "https://www.douyin.com/")
    ctx.guard("b")
    last_error: Exception | None = None
    try:
        payload = None
        # 主通道：浏览器上下文直接发请求——首页偶发跳转（验证码中间页）也打不断它
        for attempt in range(2):
            try:
                response = await page.request.get(HOT_URL, headers=HOT_HEADERS)
                if response.status == 200:
                    body = await response.text()
                    if body.strip():
                        payload = json.loads(body)
                        break
                last_error = RuntimeError(f"HTTP {response.status}")
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(1.2)
        # 兜底：页面内 fetch（旧路线）
        if not payload:
            try:
                payload = await page.evaluate("""async (url) => {
                    const response = await fetch(url, {credentials: 'include'});
                    if (!response.ok) return null;
                    return await response.json();
                }""", HOT_URL)
            except Exception as exc:
                last_error = exc
    finally:
        ctx.quota.consume("b")
    if not payload:
        raise RuntimeError(f"热点接口没有返回数据（{type(last_error).__name__}：{str(last_error)[:80]}）")
    return payload


def _extract_words(payload: Any) -> list[dict[str, Any]]:
    """容错读取：不同版本的字段名都可能出现。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    for key in ("word_list", "trending_list", "list", "hotsearch_list"):
        value = data.get(key)
        if isinstance(value, list) and value:
            words = [item for item in value
                     if isinstance(item, dict) and (item.get("word") or item.get("sentence"))]
            if words:
                return words
    return []


async def _hot(ctx, args: dict) -> dict:
    platform = str(args.get("platform") or "douyin").strip().lower()
    limit = max(1, min(20, int(args.get("limit") or 10)))
    if platform != "douyin":
        return {"ok": False, "summary": f"暂时只支持抖音热点榜（收到 {platform}）"}
    try:
        payload = await _douyin_hot(ctx)
    except Exception as exc:
        return {"ok": False, "summary": f"获取抖音热点榜失败：{type(exc).__name__}：{str(exc)[:140]}"}
    words = _extract_words(payload)[:limit]
    if not words:
        return {"ok": False, "summary": "热点榜返回空数据（接口结构可能变化）"}
    lines = []
    for index, item in enumerate(words, 1):
        title = str(item.get("word") or item.get("sentence") or "").strip()
        heat = item.get("hot_value") or item.get("heat") or item.get("hot_score")
        lines.append(f"{index}. {title}" + (f"（热度 {heat}）" if heat else ""))
    return {"ok": True, "summary": f"拿到抖音热点榜前 {len(words)} 条", "content": "\n".join(lines)}


register(ToolSpec(
    id="hot_topics", name="抖音热点榜",
    description="获取抖音实时热点榜（公开数据）。做选题、判断当前什么内容有流量时使用。",
    parameters={"type": "object",
                "properties": {"platform": {"type": "string", "enum": ["douyin"],
                                            "description": "平台，目前仅支持 douyin"},
                               "limit": {"type": "integer", "description": "条数 1-20，默认 10"}},
                "required": []},
    agents=("observer", "strategy"),  # 观察员主场；策略师做选题时需要榜单依据
    handler=_hot))
