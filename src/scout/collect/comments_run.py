"""Single-work comment collection shared by the desktop action and the AI tools."""
from __future__ import annotations

import asyncio
from dataclasses import replace


async def collect_for_work(ctx, emit, aweme_id):
    """采集单条作品的评论区：登录态 + 抽样预算 + 幂等入库。"""
    from ..collect.comments import CommentsCollector
    from ..store.collection import CollectionQueue

    aweme_id = str(aweme_id or "")
    if not aweme_id:
        raise ValueError("缺少作品标识")
    work = ctx.works.get(aweme_id) or {}
    if not work:
        raise ValueError("本地没有这条作品的记录，请先采集作品")
    tier = next((t.name for t in ctx.config.tiers.values() if t.enabled and t.mode == "logged_in"), None)
    if not tier:
        raise ValueError("没有启用登录账号")
    tiers = dict(ctx.config.tiers)
    tiers[tier] = replace(tiers[tier], use_storage_state=True)
    ctx.config = replace(ctx.config, tiers=tiers, browser=replace(ctx.config.browser, cdp_url=""))
    title = str(work.get("description") or aweme_id)[:20]
    emit({"message": f"正在采集评论区（{title}）…"})
    queue = CollectionQueue(ctx)
    task = queue.claim("fetch_comments", aweme_id, tier)
    if task is None:
        raise ValueError("这条作品的评论任务正在运行或退避中，请稍后再试")
    collector = CommentsCollector(ctx)
    collector.on_progress = emit
    try:
        outcome = await collector.run({**task, "_api_cadence": True, "_resume": True,
                                       "_hint": str(work.get("comment_count") or "")})
    except asyncio.CancelledError:
        queue.release(task)
        raise
    error = str(outcome.error or "")
    if outcome.ok:
        ctx.tasks.complete(task["id"])
    elif outcome.blocked:
        queue.release(task)
        raise ValueError(f"采集受阻：{error}")
    else:
        if error.startswith("达到页数上限"):
            queue.release(task)
        else:
            ctx.tasks.fail(task["id"], error, retry=True)
        raise ValueError(f"评论采集未完成：{error[:120]}")
    return {"aweme_id": aweme_id, "items": ctx.comments.count_for_work(aweme_id),
            "state": outcome.persisted.get("collection_state")}
