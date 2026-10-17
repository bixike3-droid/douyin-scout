"""企业侧写入工具：把用户口述的真实指标补录进来（confirm 级）。

只写 enterprise_metrics —— 采集来的数据与人工补录分开存，
来源、统计日期必须写清楚，避免把估算当实测。
"""
from __future__ import annotations

from datetime import date

from .registry import ToolSpec, register

METRIC_LABELS = {"play_count": "播放", "digg_count": "点赞",
                 "comment_count": "评论", "share_count": "分享"}


def _clean_int(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("指标须为非负整数")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("指标须为非负整数") from None
    if number < 0:
        raise ValueError("指标须为非负整数")
    return number


async def _metrics_backfill(ctx, args: dict) -> dict:
    from ..store.enterprise import EnterpriseStore

    aweme_id = str(args.get("aweme_id") or "").strip()
    if not aweme_id:
        latest = ctx.works.list(mine_only=True, limit=1)
        aweme_id = str((latest[0] or {}).get("aweme_id") or "") if latest else ""
    if not aweme_id:
        return {"ok": False, "summary": "本地还没有本人作品，请先采集作品再补录"}
    work = ctx.works.get(aweme_id) or {}
    if not work or not work.get("is_mine"):
        return {"ok": False, "summary": "只能补录本人作品，请确认作品标识后重试"}
    try:
        values = {key: _clean_int(args.get(key)) for key in METRIC_LABELS}
    except ValueError as exc:
        return {"ok": False, "summary": str(exc)}
    if all(value is None for value in values.values()):
        return {"ok": False, "summary": "至少填写一项指标（播放/点赞/评论/分享）"}
    data = {
        "aweme_id": aweme_id,
        "measured_at": str(args.get("measured_at") or date.today().isoformat()),
        "source": str(args.get("source") or "对话补录（用户提供）").strip(),
        "notes": str(args.get("notes") or "").strip(),
        **values,
    }
    try:
        EnterpriseStore(ctx.db).save_metrics(data)
    except ValueError as exc:
        return {"ok": False, "summary": str(exc)}
    shown = "｜".join(f"{label} {value:,}" for label, value in
                     ((METRIC_LABELS[k], v) for k, v in values.items()) if value is not None)
    title = str(work.get("description") or aweme_id)[:24]
    return {"ok": True,
            "summary": f"已补录 {title} 在 {data['measured_at']} 的指标：{shown}",
            "content": f"作品：{title}（{aweme_id}）\n统计日期：{data['measured_at']}\n来源：{data['source']}\n{shown}",
            "data": {"aweme_id": aweme_id, "measured_at": data["measured_at"]}}


register(ToolSpec(
    id="metrics_backfill", name="补录指标",
    description="把用户口述的抖音后台真实指标（播放/点赞/评论/分享）补录到指定作品，"
                "需要统计日期与来源。用户给出截图数字或后台数据时使用。执行前会先让用户确认。",
    parameters={"type": "object",
                "properties": {"aweme_id": {"type": "string",
                                            "description": "作品标识，留空取最新一条本人作品"},
                               "measured_at": {"type": "string",
                                               "description": "统计日期 YYYY-MM-DD，默认今天"},
                               "source": {"type": "string",
                                          "description": "数据来源，如「抖音创作者中心截图」"},
                               "play_count": {"type": "integer", "description": "播放数"},
                               "digg_count": {"type": "integer", "description": "点赞数"},
                               "comment_count": {"type": "integer", "description": "评论数"},
                               "share_count": {"type": "integer", "description": "分享数"},
                               "notes": {"type": "string", "description": "备注，可留空"}},
                "required": ["measured_at", "source"]},
    agents=("data", "content"), level="confirm",
    handler=_metrics_backfill))
