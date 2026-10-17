"""热点工具：抖音实时热点榜。

与账号采集同一套合规路线（见 scout.collect.hot）：登录档优先、页面内请求、
护栏 / 配额、原始响应落盘、快照入库。不是搜索，是抖音自己的热榜接口。
实时获取失败时回落最近一次本地快照，并在摘要里说清楚。
"""
from __future__ import annotations

from .registry import ToolSpec, register
from ..collect.hot import HOT_HEADERS, HOT_URL, HotFetchError, extract_words, fetch_hot
from ..store.hot import HotTopics

# 保留旧名字：看板与旧代码按这个注入/引用
_douyin_hot = fetch_hot
_extract_words = extract_words


async def _hot(ctx, args: dict) -> dict:
    platform = str(args.get("platform") or "douyin").strip().lower()
    limit = max(1, min(20, int(args.get("limit") or 10)))
    if platform != "douyin":
        return {"ok": False, "summary": f"暂时只支持抖音热点榜（收到 {platform}）"}
    note = ""
    try:
        payload = await _douyin_hot(ctx)
        words = extract_words(payload)[:limit]
    except Exception as exc:  # noqa: BLE001 —— 实时失败回落本地快照
        words = []
        reason = str(exc)[:140] if isinstance(exc, HotFetchError) else f"{type(exc).__name__}：{str(exc)[:120]}"
        try:
            latest = HotTopics(ctx.db).latest(limit=limit)
        except Exception:  # noqa: BLE001
            latest = None
        if latest and latest["items"]:
            words = [{"word": item["word"], "hot_value": item.get("hot_value")}
                     for item in latest["items"]]
            stamp = latest["fetched_at"][:16].replace("T", " ")
            note = f"（实时获取失败：{reason}；使用本地快照 {stamp}）"
        else:
            return {"ok": False, "summary": f"获取抖音热点榜失败：{reason}"}
    if not words:
        return {"ok": False, "summary": "热点榜返回空数据（接口结构可能变化）"}
    lines = []
    for index, item in enumerate(words, 1):
        title = str(item.get("word") or item.get("sentence") or "").strip()
        heat = item.get("hot_value") or item.get("heat") or item.get("hot_score")
        lines.append(f"{index}. {title}" + (f"（热度 {heat}）" if heat else ""))
    return {"ok": True, "summary": f"拿到抖音热点榜前 {len(words)} 条{note}", "content": "\n".join(lines)}


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
