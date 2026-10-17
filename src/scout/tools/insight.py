"""洞察类工具：趋势、单作品详情、历史报告（全部只读、无外网）。

数据源与界面完全一致：works / like_edges / comments / enterprise_metrics /
enterprise_reports。任何数字都附时间与样本量，方便在对话里复核。
"""
from __future__ import annotations

import json
import time

from .registry import ToolSpec, register

METRIC_NAMES = {"play_count": "播放", "digg_count": "点赞", "comment_count": "评论",
                "share_count": "分享", "collect_count": "收藏"}
TREND_METRICS = ("play_count", "digg_count", "comment_count", "share_count", "collect_count")
DAY = 86400


def _pct(current: float, previous: float) -> str:
    if not previous:
        return "无法比较" if current else "0"
    rate = (current - previous) / previous * 100
    return f"{rate:+.1f}%"


def _fmt(value) -> str:
    return "未知" if value is None else f"{int(value):,}"


def _mine_works(ctx, limit: int):
    return ctx.db.rows_as_dicts(
        "SELECT aweme_id,description,create_time,play_count,digg_count,comment_count,"
        "share_count,collect_count FROM works WHERE is_mine=1 AND create_time IS NOT NULL "
        "ORDER BY create_time DESC LIMIT ?", (limit,))


async def _analytics_trend(ctx, args: dict) -> dict:
    days = int(args.get("days") or 30)
    days = max(1, min(180, days))
    metric = str(args.get("metric") or "play_count").strip()
    if metric not in TREND_METRICS:
        return {"ok": False, "summary": "metric 只能是 " + " / ".join(TREND_METRICS)}
    rows = _mine_works(ctx, 200)
    if not rows:
        return {"ok": False, "summary": "本地还没有本人作品数据，请先完成一次采集"}
    now = int(time.time())
    recent_from = now - days * DAY
    previous_from = recent_from - days * DAY
    recent = [r for r in rows if int(r["create_time"] or 0) >= recent_from]
    previous = [r for r in rows if previous_from <= int(r["create_time"] or 0) < recent_from]

    def total(items):
        return sum(int(r.get(metric) or 0) for r in items)

    def average(items):
        return total(items) / len(items) if items else 0.0

    label = METRIC_NAMES[metric]
    lines = [
        f"窗口：近 {days} 天 {len(recent)} 条 vs 前 {days} 天 {len(previous)} 条（按发布时间）",
        f"{label}总量：{_fmt(total(recent))} vs {_fmt(total(previous))}（{_pct(total(recent), total(previous))}）",
        f"{label}均值：{average(recent):.0f} vs {average(previous):.0f}"
        f"（{_pct(average(recent), average(previous))}）",
    ]
    ranked = sorted(recent, key=lambda r: int(r.get(metric) or 0), reverse=True)[:5]
    if ranked:
        lines.append("近期前列：")
        lines.extend(f"- {str(r.get('description') or '（无标题）')[:30]}｜"
                     f"{label} {_fmt(r.get(metric))}｜发布 {time.strftime('%Y-%m-%d', time.localtime(int(r['create_time'])))}"
                     for r in ranked)
    if not previous:
        lines.append("注意：前一周期没有作品，环比只能作参考。")
    summary = (f"近 {days} 天{label} {_fmt(total(recent))}，环比 {_pct(total(recent), total(previous))}；"
               f"样本 {len(recent)} 条")
    return {"ok": True, "summary": summary, "content": "\n".join(lines),
            "data": {"days": days, "metric": metric, "recent": len(recent), "previous": len(previous),
                     "recent_total": total(recent), "previous_total": total(previous)}}


async def _work_detail(ctx, args: dict) -> dict:
    aweme_id = str(args.get("aweme_id") or "").strip()
    if aweme_id:
        work = ctx.works.get(aweme_id)
    else:
        latest = ctx.works.list(mine_only=True, limit=1)
        work = latest[0] if latest else None
        aweme_id = str((work or {}).get("aweme_id") or "")
    if not work:
        return {"ok": False, "summary": "本地没有这条作品的记录，请先采集作品" if aweme_id
                else "本地还没有本人作品数据，请先完成一次采集"}
    likers = dict(ctx.db.query_one(
        "SELECT COUNT(DISTINCT sec_uid) AS n FROM like_edges WHERE aweme_id=?", (aweme_id,)) or {})
    comments_total = ctx.comments.count_for_work(aweme_id)
    top = ctx.comments.list_for_work(aweme_id, limit=5)
    manual_row = ctx.db.query_one(
        "SELECT measured_at,source,play_count,digg_count,comment_count,share_count FROM enterprise_metrics "
        "WHERE aweme_id=? ORDER BY measured_at DESC,id DESC LIMIT 1", (aweme_id,))
    manual = dict(manual_row) if manual_row else None
    tags = []
    try:
        tags = [str(t) for t in json.loads(work.get("hashtags_json") or "[]")][:6]
    except (ValueError, TypeError):
        tags = []
    lines = [f"作品：{str(work.get('description') or '（无标题）')[:60]}",
             f"发布：{time.strftime('%Y-%m-%d %H:%M', time.localtime(int(work['create_time']))) if work.get('create_time') else '未知'}"
             f"｜时长：{(int(work.get('duration_ms') or 0) / 1000):.0f}s"]
    lines.append("｜".join(f"{METRIC_NAMES[k]} {_fmt(work.get(k))}" for k in
                           ("play_count", "digg_count", "comment_count", "share_count", "collect_count")))
    lines.append(f"本地证据：已采点赞人 {likers.get('n', 0)} 人｜已采评论 {comments_total} 条")
    if tags:
        lines.append("话题：" + " ".join(tags))
    if manual:
        lines.append(f"人工补录（{manual['measured_at']}，{manual['source'][:20]}）："
                     + "｜".join(f"{METRIC_NAMES[k]} {_fmt(manual.get(k))}"
                                 for k in ("play_count", "digg_count", "comment_count", "share_count")))
    if top:
        lines.append("高赞评论：")
        lines.extend(f"- {str(c.get('text') or '')[:40]}｜赞 {_fmt(c.get('digg_count'))}"
                     for c in top)
    elif comments_total == 0:
        lines.append("评论：这条作品还没有采评论，可用 collect_comments 采集。")
    summary = (f"{str(work.get('description') or aweme_id)[:24]}：点赞 {_fmt(work.get('digg_count'))}，"
               f"评论 {_fmt(work.get('comment_count'))}，已采评论 {comments_total} 条")
    return {"ok": True, "summary": summary, "content": "\n".join(lines),
            "data": {"aweme_id": aweme_id, "likers": int(likers.get("n") or 0),
                     "comments": comments_total}}


async def _report_read(ctx, args: dict) -> dict:
    from ..store.enterprise import EnterpriseStore

    store = EnterpriseStore(ctx.db)
    report_id = int(args.get("report_id") or 0)
    if report_id:
        try:
            report = store.report(report_id)
        except ValueError as exc:
            return {"ok": False, "summary": str(exc)}
    else:
        rows = store.reports()
        if not rows:
            return {"ok": False, "summary": "还没有历史推广报告，先在「企业分析」里生成一份"}
        report = store.report(int(rows[0]["id"]))
    output = report.get("output") or {}
    title = (report.get("input") or {}).get("request") or f"传播报告 {report.get('id')}"
    lines = [f"报告 #{report.get('id')}：{str(title)[:40]}",
             f"生成于 {report.get('created_at')}｜模型 {report.get('model')}"
             f"｜人工复核 {len(report.get('revisions') or [])} 次"]
    for key, label in (("diagnosis", "传播问题"), ("optimization", "内容优化"),
                       ("topics", "个性化选题"), ("strategy", "传播策略")):
        items = output.get(key) or []
        if not items:
            continue
        lines.append(f"{label}：")
        for item in items[:5]:
            text = item.get("title") if key == "topics" else item.get("text")
            evidence = "、".join(str(e) for e in (item.get("evidence_ids") or [])[:3])
            lines.append(f"- {str(text or '')[:90]}" + (f"（{evidence}）" if evidence else ""))
    notes = output.get("measurement") or []
    if notes:
        lines.append("测量与验证：" + "；".join(str(n)[:60] for n in notes[:4]))
    body = "\n".join(lines)
    if len(body) > 3000:
        body = body[:3000] + "…（已截断，可指定 report_id 查看另一份）"
    return {"ok": True, "summary": f"已读取报告 #{report.get('id')}（{report.get('created_at')}）",
            "content": body, "data": {"report_id": report.get("id")}}


register(ToolSpec(
    id="analytics_trend", name="数据趋势",
    description="按发布时间对比近期与上一周期的作品表现（播放/点赞/评论/分享/收藏的环比与均值），"
                "并列出近期表现最好的几条。用户问「最近数据怎么样/涨了还是跌了」时使用。",
    parameters={"type": "object",
                "properties": {"days": {"type": "integer", "description": "对比周期天数，1-180，默认 30"},
                               "metric": {"type": "string", "enum": list(TREND_METRICS),
                                          "description": "关注指标，默认 play_count"}}},
    agents=("content", "review", "steward"), level="read",
    handler=_analytics_trend))

register(ToolSpec(
    id="work_detail", name="作品详情",
    description="查看一条作品的全部细节：发布信息、各项指标、已采点赞人数、已采评论数、"
                "高赞评论和人工补录指标。不传 aweme_id 时看最新一条本人作品。",
    parameters={"type": "object",
                "properties": {"aweme_id": {"type": "string",
                                            "description": "作品标识，留空取最新一条本人作品"}}},
    agents=("content", "audience", "review", "strategy", "steward", "data"), level="read",
    handler=_work_detail))

register(ToolSpec(
    id="report_read", name="读取历史报告",
    description="读取已生成的推广分析报告（传播问题、内容优化、选题、策略、验证方式）。"
                "用户问「上次报告怎么说的/复盘一下」时使用；不传 report_id 取最新一份。",
    parameters={"type": "object",
                "properties": {"report_id": {"type": "integer", "description": "报告编号，留空取最新"}}},
    agents=("review", "strategy", "steward"), level="read",
    handler=_report_read))
