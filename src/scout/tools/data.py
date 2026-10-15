"""数据工具：数据管家查询本机已采集的数据（只读、无外网）。

复用桌面端同一套查询（store.desktop），保证工具看到的和界面里的一致。
"""
from __future__ import annotations

from .registry import ToolSpec, register
from ..store.desktop import DesktopStore

VIEW_NAMES = {"users": "互动者", "works": "作品", "analyses": "历史分析", "tasks": "采集任务"}
STATE_NAMES = {"pending": "待处理", "running": "执行中", "done": "已完成", "failed": "失败", "blocked": "已暂停"}


def _overview_text(data: dict) -> str:
    self_info = data.get("self") or {}
    lines = [
        f"账号：{self_info.get('nickname') or '（尚未识别，先完成登录采集）'}",
        f"作品 {data.get('works', 0)} 条｜互动者 {data.get('users', 0)} 人｜"
        f"分析结果 {data.get('analyses', 0)} 份｜待处理任务 {data.get('pending', 0)} 个",
    ]
    counts = data.get("task_counts") or {}
    if counts:
        lines.append("任务状态：" + "，".join(
            f"{STATE_NAMES.get(key, key)} {value}" for key, value in sorted(counts.items())))
    recent = data.get("recent_works") or []
    if recent:
        lines.append("最近作品：" + "；".join(
            str(item.get("description") or "（无标题）")[:24] for item in recent))
    events = (data.get("events") or [])[:3]
    if events:
        lines.append("最近动态：" + "；".join(
            str(item.get("message") or "")[:40] for item in events))
    return "\n".join(lines)


async def _overview(ctx, args: dict) -> dict:
    data = DesktopStore(ctx.db).overview()
    return {"ok": True, "summary": "已读取本机数据概览", "content": _overview_text(data)}


def _row_line(view: str, row: dict) -> str:
    if view == "users":
        return (f"- {row.get('nickname') or '（无昵称）'}｜互动作品 {row.get('interaction_works', 0)}｜"
                f"粉丝 {row.get('follower_count') or '未知'}｜资料 {row.get('data_status') or '未知'}")
    if view == "works":
        return (f"- {str(row.get('description') or '（无标题）')[:40]}｜点赞 {row.get('digg_count', 0)}｜"
                f"评论 {row.get('comment_count', 0)}｜发布 {row.get('create_time') or '未知'}")
    if view == "tasks":
        state = STATE_NAMES.get(row.get("state"), row.get("state") or "")
        return (f"- {row.get('kind') or ''} {str(row.get('target') or '')[:30]}｜{state}｜"
                f"尝试 {row.get('attempts', 0)} 次")
    return (f"- {str(row.get('input_summary') or '')[:45]}｜{row.get('task') or ''}｜"
            f"{row.get('created_at') or ''}")


async def _records_search(ctx, args: dict) -> dict:
    view = str(args.get("view") or "").strip()
    if view not in VIEW_NAMES:
        return {"ok": False, "summary": "view 只能是 users / works / analyses / tasks"}
    keyword = str(args.get("query") or "").strip()
    data = DesktopStore(ctx.db).page(view, keyword)
    rows = data.get("rows") or []
    total = int(data.get("total") or 0)
    label = VIEW_NAMES[view]
    if not total:
        hint = "换个关键词试试" if keyword else "先完成一次采集"
        return {"ok": True, "summary": f"{label}里没有匹配「{keyword}」的记录", "content": f"（没有结果，{hint}）"}
    lines = [f"{label}共 {total} 条匹配，先看前 {min(len(rows), 8)} 条："]
    lines.extend(_row_line(view, row) for row in rows[:8])
    return {"ok": True, "summary": f"{label}检索「{keyword or '全部'}」：{total} 条匹配", "content": "\n".join(lines)}


register(ToolSpec(
    id="data_overview", name="数据概览",
    description="查看本机已采集数据的总体情况：作品数、互动者人数、分析结果、采集任务状态与最近作品。"
                "回答「我们手上有多少数据」「最近采了什么」这类问题前先调用。",
    parameters={"type": "object", "properties": {}},
    handler=_overview))

register(ToolSpec(
    id="records_search", name="记录检索",
    description="在本机采集数据里检索：互动者（users）、作品（works）、历史分析（analyses）、采集任务（tasks）。"
                "需要查具体某个人、某个作品或任务状况时使用；query 可留空表示看最新的。",
    parameters={"type": "object",
                "properties": {"view": {"type": "string", "enum": ["users", "works", "analyses", "tasks"],
                                        "description": "检索哪类记录"},
                               "query": {"type": "string", "description": "关键词（昵称 / 标题 / 标识），可留空"}},
                "required": ["view"]},
    handler=_records_search))
