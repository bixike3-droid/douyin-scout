"""后台数据截图 → 指标（Vision）。

只做识别，不直接入库：结果回填表单，必须人工核对后再保存快照。
截图里看不清的字段一律 null，不猜。
"""
from __future__ import annotations

import json
import re

from ..llm import LLMReply

PROMPT = """这是抖音创作者中心的作品数据截图。请读取截图，严格按 JSON 返回：
{"play_count": 整数或 null, "digg_count": 整数或 null, "comment_count": 整数或 null,
 "share_count": 整数或 null, "collected_at": "YYYY-MM-DD" 或 null,
 "confidence": "high" | "medium" | "low",
 "missing": ["看不清或不存在的字段名"], "notes": "读数依据一句话"}
规则：只填截图上能看到的数字；看不清就 null 并放进 missing；不要猜测；不要输出解释。"""

METRIC_KEYS = ("play_count", "digg_count", "comment_count", "share_count")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_metrics(text: str) -> dict:
    """解析模型输出；无法使用时返回 {ok: False, error}。"""
    match = re.search(r"\{.*\}", (text or "").strip(), re.S)
    data = None
    if match:
        try:
            data = json.loads(match.group(0))
        except ValueError:
            data = None
    if not isinstance(data, dict):
        return {"ok": False, "error": "模型输出无法解析为 JSON"}
    out: dict = {}
    for key in METRIC_KEYS:
        value = data.get(key)
        try:
            out[key] = int(value) if value is not None and str(value).strip() != "" else None
        except (TypeError, ValueError):
            out[key] = None
    date = str(data.get("collected_at") or "").strip()[:10]
    out["collected_at"] = date if DATE_RE.match(date) else None
    out["confidence"] = str(data.get("confidence") or "").strip().lower()[:10]
    out["missing"] = [str(item)[:20] for item in (data.get("missing") or [])][:6]
    out["notes"] = str(data.get("notes") or "").strip()[:120]
    if not any(out[key] is not None for key in METRIC_KEYS):
        return {"ok": False, "error": "截图里没有识别到任何指标，请换清晰截图"}
    return {"ok": True, "data": out}


async def recognize(client, image_path) -> dict:
    reply: LLMReply = await client.vision_json(PROMPT, image_path)
    result = parse_metrics(reply.text)
    result["model"] = reply.model
    return result
