"""热点看板：抖音实时热点 + AI 可用性评估（供右侧「抖音热点」面板使用）。

抓取复用 tools.hot 的合规路线（真实浏览器、页面内 fetch）；
评估用一次小调用把「企业资料 + 热点列表」交给模型，逐条打标记：
可用（能直接做内容）/ 参考（间接相关）/ 无关（硬蹭伤调性）。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from ..util import iso
from .ai import _parse_json

MARKS = ("可用", "参考", "无关")

EVAL_SYSTEM = """你是内容运营的热点雷达。用户会给出企业资料和一份抖音实时热点榜，请逐条判断该热点对本企业内容运营的可利用性：
- 可用：与行业/客群/场景自然相关，能直接做内容或轻借势
- 参考：间接相关，或只能作为背景/情绪素材，价值一般
- 无关：与业务几乎没有关系，硬蹭会损伤账号调性
只输出 JSON：{"marks":[{"i":1,"mark":"可用|参考|无关","why":"不超过14字的具体理由"}]}。
必须覆盖给出的每一条序号；判断要基于资料，不要脑补企业没提供的信息。"""

PROFILE_FIELDS = (("name", "企业名称"), ("location", "经营地点"), ("goal", "传播目标"),
                  ("audience", "目标客群"), ("features", "特色"), ("offer", "提供"),
                  ("constraints", "约束"))


def profile_digest(profile: dict) -> str:
    parts = [f"{label}：{profile[key]}" for key, label in PROFILE_FIELDS
             if isinstance(profile.get(key), str) and profile[key].strip()]
    return "；".join(parts) or "（企业资料尚未填写，按通用内容运营判断）"


async def evaluate_topics(profile_text: str, words: list[dict], client) -> dict[int, dict]:
    """返回 {序号: {"mark": ..., "why": ...}}；解析失败的条目直接缺席。"""
    listing = "\n".join(
        f"{index}. {item['word']}（热度 {item.get('heat') or '未知'}）" for index, item in enumerate(words, 1))
    reply = await client.chat(EVAL_SYSTEM, json.dumps({"企业资料": profile_text, "热点榜": listing},
                                                      ensure_ascii=False),
                              json_mode=True, max_tokens=2000, thinking=False)
    data = _parse_json(reply.text)
    marks: dict[int, dict] = {}
    if not isinstance(data, dict):
        return marks
    for item in data.get("marks") or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        mark = str(item.get("mark") or "").strip()
        if mark in MARKS and index > 0:
            marks[index] = {"mark": mark, "why": str(item.get("why") or "").strip()[:40]}
    return marks


async def load_hot_board(ctx, *, client=None, fetch: Callable | None = None, limit: int = 20,
                       headless: bool = False) -> dict:
    """抓热点 + 评估，返回面板可直接展示的结构；一切失败都转成 error 字段。"""
    from ..tools.hot import _extract_words  # 延迟导入，测试可注入 fetch
    from ..collect.hot import fetch_hot

    snapshot_note = ""
    try:
        payload = await (fetch or (lambda context: fetch_hot(context, headless=headless)))(ctx)
        raw = _extract_words(payload)
    except Exception as exc:  # noqa: BLE001 —— 实时失败回落本地快照
        latest = _recent_snapshot(ctx)
        if latest is None:
            return {"error": f"热点获取失败：{type(exc).__name__}：{str(exc)[:120]}", "fetched_at": iso()}
        raw = [{"word": item["word"], "hot_value": item.get("hot_value")}
               for item in latest["items"]]
        stamp = latest["fetched_at"][:16].replace("T", " ")
        snapshot_note = f"实时获取失败（{str(exc)[:80]}），展示本地快照（{stamp}）"
    if not raw:
        return {"error": "热点榜返回为空（接口结构可能变化）", "fetched_at": iso()}

    words: list[dict[str, Any]] = []
    for item in raw[:max(1, limit)]:
        words.append({"word": str(item.get("word") or item.get("sentence") or "").strip(),
                      "heat": item.get("hot_value") or item.get("heat") or item.get("hot_score") or "",
                      "mark": "", "why": ""})

    notes = [snapshot_note] if snapshot_note else []
    if not getattr(getattr(ctx.config, "llm", None), "api_key", ""):
        notes.append("未配置模型 Key，暂不做可用性评估")
    else:
        try:
            if client is None:
                from ..llm import DeepSeekClient
                client = DeepSeekClient(ctx.config.llm)
            from ..store.enterprise import EnterpriseStore
            profile = EnterpriseStore(ctx.db).profile()
            marks = await evaluate_topics(profile_digest(profile), words, client)
            for index, item in enumerate(words, 1):
                hit = marks.get(index)
                if hit:
                    item["mark"] = hit["mark"]
                    item["why"] = hit["why"]
            if not marks:
                notes.append("评估结果为空（模型输出未通过校验）")
        except Exception as exc:  # noqa: BLE001 —— 评估失败不影响榜单展示
            notes.append(f"可用性评估暂不可用（{type(exc).__name__}）")

    return {"topics": words, "fetched_at": iso(), "note": "；".join(notes),
            "usable": sum(1 for item in words if item.get("mark") == "可用")}


def _recent_snapshot(ctx):
    """本地最近一份热榜快照；读不到（旧库/无记录）返回 None。"""
    try:
        from ..store.hot import HotTopics
        latest = HotTopics(ctx.db).latest(limit=50)
    except Exception:  # noqa: BLE001
        return None
    return latest if latest and latest.get("items") else None
