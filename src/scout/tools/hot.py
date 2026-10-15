"""热点工具：抖音实时热点榜。

与采集同一套合规路线：真实浏览器里由页面自身发起请求，程序只读响应。
失败（未开档位 / 触发验证 / 结构变化）都转成清晰的工具结果，不抛给对话。
"""
from __future__ import annotations

from typing import Any

from .registry import ToolSpec, register
from ..collect.api_base import COMMON_PARAMS

# 实测（2026-10-15，匿名档 b）：该接口不需要签名，页面内 fetch 返回 50 条；
# 注意不能带 source=trending_page（接口要求 source 为整数，传字符串会 400）。
HOT_URL = ("https://www.douyin.com/aweme/v1/web/hot/search/list/?" + COMMON_PARAMS
           + "&detail_list=1")


async def _douyin_hot(ctx) -> dict:
    session = await ctx.open_session()
    page = await session.goto("b", "https://www.douyin.com/")
    ctx.guard("b")
    try:
        payload = await page.evaluate("""async (url) => {
            const response = await fetch(url, {credentials: 'include'});
            if (!response.ok) return null;
            return await response.json();
        }""", HOT_URL)
    finally:
        ctx.quota.consume("b")
    if not payload:
        raise RuntimeError("热点接口没有返回数据（可能触发了验证或页面结构变化）")
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
    handler=_hot))
