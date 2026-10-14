"""Desktop login, collection and analysis operations with scoped resources."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from ..app import AppContext
from ..config import load_config
from ..collect.self_profile import API_URL, SelfCollector
from ..parse.registry import parse_payload
from ..session.lock import ProfileLock
from ..session.health import LOGIN_COOKIES


def login_status(paths):
    cfg = load_config(paths)
    tier = next((t.name for t in cfg.tiers.values() if t.enabled and t.mode == "logged_in"), None)
    state = paths.state_dir / f"tier_{tier}_storage.json" if tier else None
    saved = False
    if state and state.is_file():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            cookies = data.get("cookies", []) if isinstance(data, dict) else []
            saved = any(c.get("name") in LOGIN_COOKIES
                        and (c.get("domain") or "").lstrip(".") in ("douyin.com", "www.douyin.com")
                        and (float(c.get("expires", -1)) < 0 or float(c.get("expires", -1)) > time.time())
                        for c in cookies)
        except (ValueError, TypeError, OSError):
            pass
    return {"saved": saved, "tier": tier,
            "message": "已保存登录态，使用前会验证" if saved else "请登录抖音后开始采集"}


async def probe_identity(page):
    """Identity is confirmed by the self-profile API, never by a nickname alone."""
    return await asyncio.wait_for(page.evaluate("""async (url) => {
        const r = await fetch(url, {credentials: 'include'});
        if (!r.ok) return null;
        const p = await r.json();
        return p.status_code === 0 && p.user && p.user.sec_uid ? p : null;
    }""", API_URL), timeout=12)


def save_identity(ctx, payload):
    uid = (payload.get("user") or {}).get("sec_uid")
    if not uid:
        raise ValueError("未能确认抖音账号")
    previous = ctx.cursors.get("self_sec_uid")
    if previous and previous != uid:
        raise ValueError("当前数据属于另一抖音账号，请使用独立的数据目录登录，避免混合账号数据")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw = ctx.archive.save(body, url=API_URL, tier="a", content_type="application/json", source="login")
    parsed = parse_payload(API_URL, payload, raw_blob_id=raw.id)
    with ctx.db.transaction():
        SelfCollector(ctx).persist(parsed, {})
    return (payload.get("user") or {}).get("nickname") or "你的抖音账号"


async def export_state(context, target):
    """Atomic export; cancel/failure cannot truncate the previous login state."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".login-", suffix=".json", dir=target.parent)
    os.close(fd)
    try:
        await context.storage_state(path=temporary)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


async def login(ctx, emit, *, timeout=300, poll_interval=2):
    from playwright.async_api import async_playwright

    tier = next((t for t in ctx.config.tiers.values() if t.enabled and t.mode == "logged_in"), None)
    if tier is None:
        raise ValueError("没有启用登录账号，请检查配置")
    emit({"message": "正在打开登录浏览器…"})
    with ProfileLock(tier.resolved_profile_dir(ctx.paths)):
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(tier.resolved_profile_dir(ctx.paths)),
                headless=False, channel=ctx.config.browser.channel or None,
                locale=ctx.config.browser.locale, timezone_id=ctx.config.browser.timezone,
                viewport={"width": 1280, "height": 800},
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(ctx.config.targets.home_url, wait_until="domcontentloaded", timeout=45000)
                emit({"message": "请在打开的浏览器中点击登录并扫码；出现验证码时可直接操作。登录成功后会自动返回。"})
                deadline = time.monotonic() + timeout
                last_probe = 0.0
                last_cookies = None
                while time.monotonic() < deadline:
                    if page.is_closed():
                        raise ValueError("登录浏览器已关闭，请重新点击登录")
                    cookies = await context.cookies()
                    fingerprint = tuple(sorted((c.get("name", ""), c.get("value", ""))
                                               for c in cookies if c.get("name") in LOGIN_COOKIES))
                    payload = None
                    if last_probe == 0 or (fingerprint and (fingerprint != last_cookies or time.monotonic() - last_probe >= 10)):
                        last_probe = time.monotonic()
                        last_cookies = fingerprint
                        try:
                            payload = await probe_identity(page)
                        except Exception:
                            # Verification pages may not yet allow the self-profile request.
                            payload = None
                    if payload:
                        previous = ctx.cursors.get("self_sec_uid")
                        uid = payload["user"]["sec_uid"]
                        if previous and previous != uid:
                            raise ValueError("当前数据属于另一抖音账号，请使用独立的数据目录登录")
                        await export_state(context, ctx.paths.state_dir / f"tier_{tier.name}_storage.json")
                        nickname = save_identity(ctx, payload)
                        ctx.db.log_event("info", "login", f"桌面登录成功：{nickname}")
                        return {"message": f"登录成功：{nickname}", "nickname": nickname}
                    await asyncio.sleep(poll_interval)
                raise TimeoutError("登录超时，请重新点击登录并完成扫码")
            finally:
                await context.close()


async def collect(ctx, emit, options):
    from ..schedule import Engine

    tier = next((t.name for t in ctx.config.tiers.values() if t.enabled and t.mode == "logged_in"), None)
    if not tier:
        raise ValueError("没有启用登录账号")
    if not login_status(ctx.paths)["saved"]:
        raise ValueError("请先点击窗口顶部的「登录抖音」")
    tiers = dict(ctx.config.tiers)
    tiers[tier] = replace(tiers[tier], use_storage_state=True)
    ctx.config = replace(ctx.config, tiers=tiers, browser=replace(ctx.config.browser, cdp_url=""))
    emit({"message": "正在验证登录态…"})
    session = await ctx.open_session()
    page = await session.goto(tier, ctx.config.targets.home_url)
    ctx.guard(tier)
    try:
        payload = await probe_identity(page)
    finally:
        ctx.quota.consume(tier)
    if not payload:
        raise ValueError("登录态已失效，请重新登录抖音")
    save_identity(ctx, payload)
    kinds = options.get("kinds") or "quick"
    if kinds in ("quick", "deep"):
        from ..collect.pipeline import Pipeline
        report = await Pipeline(ctx, emit).run(mode=kinds, limit=options.get("limit", 40),
            force=bool(options.get("force")), targets=options.get("targets"), works_limit=options.get("works_limit"))
        quality = report.get("quality", {})
        return {"message": f"采集结束：完成 {report['ok']} 项（采样 {report['sampled']}），"
                f"复用缓存 {report['cached']}，部分完成 {report['partial']}，失败 {report['failed']}；"
                f"有效互动者 {quality.get('active_users', 0)} 人。{report['stop_reason']} {'；'.join(report['warnings'])}", "report": report}
    engine = Engine(ctx)
    emit({"message": "正在盘点采集任务…"})
    counts = engine.seed()
    emit({"message": "采集开始", "counts": counts})
    report = await engine.run_round(max_tasks=options.get("limit") or None,
        kinds=[kinds] if kinds else None, on_event=emit)
    return {"message": f"本轮采集结束：成功 {report.ok}，失败 {report.failed}，空结果 {report.empty}。{report.stop_reason}",
            "report": report.to_dict()}


async def analyze(ctx, kind, emit, options):
    from ..analyze.ai import analyze_many, pending_targets
    from ..analyze.creator import analyze_plan, analyze_review
    from ..llm import DeepSeekClient

    client = DeepSeekClient(ctx.config.llm)
    if kind == "profile":
        targets = pending_targets(ctx, force=bool(options.get("force")), limit=options.get("limit", 30))
        results = await analyze_many(ctx, client, targets, force=bool(options.get("force")), on_progress=emit)
        return {"message": f"画像分析结束：成功 {sum(r['ok'] for r in results)}，失败 {sum(not r['ok'] for r in results)}"}
    emit({"message": "正在生成作品评价…" if kind == "review" else "正在生成内容计划…"})
    result = await (analyze_review(ctx, client, force=bool(options.get("force"))) if kind == "review"
                    else analyze_plan(ctx, client, force=bool(options.get("force"))))
    if not result.ok:
        raise ValueError(result.error)
    return {"message": "作品评价已保存" if kind == "review" else "内容计划已保存"}


async def execute(paths, kind, emit, options=None):
    if kind not in ("login", "collect", "profile", "review", "plan", "enterprise", "chat"):
        raise ValueError("未知操作")
    ctx = AppContext.create(load_config(paths))
    try:
        if kind == "chat":
            from ..analyze.conversation import send
            from ..llm import DeepSeekClient
            options = options or {}
            return await send(ctx, DeepSeekClient(ctx.config.llm), options.get("request", ""),
                conversation_id=options.get("conversation_id"), want_plan=bool(options.get("want_plan")), emit=emit)
        if kind == "enterprise":
            from ..analyze.enterprise import generate
            from ..llm import DeepSeekClient
            emit({"message": "正在结合企业特色和作品证据生成传播建议…"})
            result = await generate(ctx, DeepSeekClient(ctx.config.llm), force=bool((options or {}).get("force")), emit=emit)
            return {"message": "已复用相同输入的推广报告" if result["cached"] else "推广报告已生成，请复核后使用", **result}
        if kind == "login":
            return await login(ctx, emit)
        if kind == "collect":
            return await collect(ctx, emit, options or {})
        return await analyze(ctx, kind, emit, options or {})
    finally:
        try:
            if ctx.session is not None:
                await ctx.session.stop()
        finally:
            ctx.close()
