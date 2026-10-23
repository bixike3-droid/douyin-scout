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


# 登录凭据：重新登录时只清这些，设备指纹（UIFID/ttwid/msToken）必须留着。
SESSION_COOKIES = (
    "sessionid", "sessionid_ss", "sid_tt", "uid_tt", "uid_tt_ss", "sid_guard",
    "sid_ucp_v1", "ssid_ucp_v1", "passport_csrf_token", "passport_csrf_token_default",
    "passport_auth_mix_state", "passport_assist_user", "passport_mfa_token",
    "session_tlb_tag", "d_ticket", "lt", "login_time", "is_staff_user",
    "x_tt_token", "web_sign_token", "has_biz_token", "fg_uid", "n_mh",
)


async def clear_login_cookies(context):
    """退出当前抖音登录，但保留设备指纹。

    把 UIFID 一起清掉会让接口马上被判风控：实测 `/aweme/v1/web/aweme/post/`
    直接返回「Blocked by ArgusSecurityPlugin Uifid Not Found」，要等页面重新
    种上设备 cookie 才能恢复。所以这里逐个按名字清登录凭据。
    """
    for name in SESSION_COOKIES:
        try:
            await context.clear_cookies(name=name)
        except TypeError:          # 老版本 Playwright 不支持按名字清
            cookies = await context.cookies()
            keep = [c for c in cookies if c.get("name") not in SESSION_COOKIES]
            await context.clear_cookies()
            if keep:
                await context.add_cookies(keep)
            return


def login_status(paths):
    cfg = load_config(paths)
    tier = next((t.name for t in cfg.tiers.values() if t.enabled and t.mode == "logged_in"), None)
    state = paths.state_dir / f"tier_{tier}_storage.json" if tier else None
    saved = False
    present: list[str] = []
    if state and state.is_file():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            cookies = data.get("cookies", []) if isinstance(data, dict) else []
            valid = [c for c in cookies
                     if (c.get("domain") or "").lstrip(".") in ("douyin.com", "www.douyin.com")
                     and (float(c.get("expires", -1)) < 0 or float(c.get("expires", -1)) > time.time())]
            # 只记名字、不记值：字段清单用于诊断，不能把凭据漏到界面/日志里。
            present = sorted({str(c.get("name") or "") for c in valid if c.get("name")})
            # 只有 sessionid 能证明拿到的是登录态；缺它再多其它 cookie 都只是游客。
            saved = "sessionid" in present
        except (ValueError, TypeError, OSError):
            present = []
    if saved:
        message = "已保存登录态，使用前会验证"
    elif present:
        message = "登录态缺少 sessionid，请重新登录"
    else:
        message = "请登录抖音后开始采集"
    return {"saved": saved, "tier": tier, "cookies": present, "message": message}


async def probe_identity(page):
    """Identity is confirmed by the self-profile API, never by a nickname alone."""
    return await asyncio.wait_for(page.evaluate("""async (url) => {
        const r = await fetch(url, {credentials: 'include'});
        if (!r.ok) return null;
        const p = await r.json();
        return p.status_code === 0 && p.user && p.user.sec_uid ? p : null;
    }""", API_URL), timeout=12)


def save_identity(ctx, payload, *, allow_switch=False):
    uid = (payload.get("user") or {}).get("sec_uid")
    if not uid:
        raise ValueError("未能确认抖音账号")
    previous = ctx.cursors.get("self_sec_uid")
    switched = bool(previous) and previous != uid
    if switched and not allow_switch:
        raise ValueError("当前数据属于另一抖音账号，请使用独立的数据目录登录，避免混合账号数据")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    raw = ctx.archive.save(body, url=API_URL, tier="a", content_type="application/json", source="login")
    parsed = parse_payload(API_URL, payload, raw_blob_id=raw.id)
    with ctx.db.transaction():
        if switched:
            # 换了账号：旧账号的作品不能再算「本人作品」，否则概览会混着两个号
            ctx.db.execute("UPDATE works SET is_mine=0 WHERE is_mine=1")
        SelfCollector(ctx).persist(parsed, {})
    if switched:
        ctx.db.log_event("warning", "login", f"抖音账号已切换：{previous} → {uid}")
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
    # 登录入口一律先清掉浏览器里的旧 cookie：profile 是持久化的，不清的话
    # 已登录的旧账号会立刻通过身份探测，用户根本没机会扫另一个号。
    previous_login = bool(login_status(ctx.paths)["saved"])
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
                await clear_login_cookies(context)
                if previous_login:
                    emit({"message": "已退出上一次的抖音登录，请在浏览器中扫码登录（可换账号）…"})
                else:
                    emit({"message": "请在打开的浏览器中点击登录并扫码；出现验证码时可直接操作。登录成功后会自动返回。"})
                await page.goto(ctx.config.targets.home_url, wait_until="domcontentloaded", timeout=45000)
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
                        await export_state(context, ctx.paths.state_dir / f"tier_{tier.name}_storage.json")
                        nickname = save_identity(ctx, payload, allow_switch=True)
                        switched = bool(previous) and previous != uid
                        ctx.db.log_event("info", "login",
                                         f"桌面登录成功：{nickname}" + (f"（原账号 {previous}）" if switched else ""))
                        message = (f"已切换账号：{nickname}（旧账号作品不再计入本人作品）" if switched
                                   else f"登录成功：{nickname}")
                        return {"message": message, "nickname": nickname, "switched": switched}
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


async def check_benchmarks(ctx, emit, options):
    """逐个检查对标账号最近作品：复用作品采集器，采集前后差集 = 新增。"""
    from ..collect.user_works_api import UserWorksApiCollector
    from ..store.benchmark import Benchmarks
    from ..store.collection import CollectionQueue

    if not login_status(ctx.paths)["saved"]:
        raise ValueError("请先点击窗口顶部的「登录抖音」")
    store = Benchmarks(ctx.db)
    accounts = store.list()
    if options.get("sec_uid"):
        accounts = [a for a in accounts if a["sec_uid"] == options["sec_uid"]]
    if not accounts:
        raise ValueError("对标名单为空，请先在「对标账号」页添加账号")
    tier = next((t.name for t in ctx.config.tiers.values() if t.enabled and t.mode == "logged_in"), None)
    if not tier:
        raise ValueError("没有启用登录账号")
    tiers = dict(ctx.config.tiers)
    tiers[tier] = replace(tiers[tier], use_storage_state=True)
    ctx.config = replace(ctx.config, tiers=tiers, browser=replace(ctx.config.browser, cdp_url=""))
    queue = CollectionQueue(ctx)
    limit = max(1, int(options.get("limit") or 12))
    lines: list[str] = []
    total_new = 0
    for index, account in enumerate(accounts, 1):
        uid = account["sec_uid"]
        name = account.get("display_name") or uid[:14]
        emit({"message": f"正在检查对标账号 {name}（{index}/{len(accounts)}）…"})
        known = {row["aweme_id"] for row in ctx.db.query(
            "SELECT aweme_id FROM works WHERE author_sec_uid=?", (uid,))}
        task = queue.claim("fetch_user_works", uid, tier)
        if task is None:
            lines.append(f"{name}：任务排队中，本次跳过")
            continue
        collector = UserWorksApiCollector(ctx)
        collector.on_progress = emit
        try:
            outcome = await collector.run({**task, "_item_limit": limit, "_api_cadence": True,
                                           "_resume": False, "_hint": ""})
        except asyncio.CancelledError:
            queue.release(task)
            raise
        error = str(outcome.error or "")
        if outcome.ok:
            ctx.tasks.complete(task["id"])
        elif outcome.blocked:
            queue.release(task)
            store.mark_checked(uid, 0, f"采集受阻：{error}")
            lines.append(f"{name}：采集受阻（{error[:60]}）")
            break
        else:
            if error.startswith("达到页数上限"):
                queue.release(task)
            else:
                ctx.tasks.fail(task["id"], error, retry=True)
            store.mark_checked(uid, 0, error)
            lines.append(f"{name}：采集未完成（{error[:60]}）")
            if "status_code=8" in error:
                emit({"message": "登录态已失效，请重新登录后再试"})
                break
            continue
        fresh = {row["aweme_id"] for row in ctx.db.query(
            "SELECT aweme_id FROM works WHERE author_sec_uid=?", (uid,))}
        new_ids = fresh - known
        total_new += len(new_ids)
        store.mark_checked(uid, len(new_ids))
        line = f"{name}：新增 {len(new_ids)} 条" if new_ids else f"{name}：无新增"
        lines.append(line)
        emit({"message": line})
    summary = f"对标检查完成，共新增 {total_new} 条。"
    if lines:
        summary += " " + "；".join(lines[:8])
    return {"message": summary, "report": {"accounts": len(accounts), "new_works": total_new}}


async def collect_comments(ctx, emit, options):
    """采集单条作品的评论区：登录态 + 抽样预算 + 幂等入库。"""
    from ..collect.comments_run import collect_for_work

    if not login_status(ctx.paths)["saved"]:
        raise ValueError("请先点击窗口顶部的「登录抖音」")
    result = await collect_for_work(ctx, emit, (options or {}).get("aweme_id"))
    note = {"sampled": "（按抽样预算采集）", "full": "（已触底）"}.get(result["state"], "")
    return {"message": f"评论区采集完成：本作品已采 {result['items']} 条评论{note}",
            "report": {"aweme_id": result["aweme_id"], "items": result["items"], "state": result["state"]}}


async def execute(paths, kind, emit, options=None):
    if kind not in ("login", "collect", "profile", "review", "plan", "enterprise", "chat", "benchmark", "comments", "chat_fork", "chat_compact"):
        raise ValueError("未知操作")
    ctx = AppContext.create(load_config(paths))
    try:
        if kind in ("chat_fork", "chat_compact"):
            from ..analyze.codex_sessions import manage
            return await manage(ctx, (options or {})["conversation_id"], "fork" if kind == "chat_fork" else "compact", emit)
        if kind == "chat":
            from ..analyze.conversation import send
            from ..llm import DeepSeekClient
            options = options or {}
            confirm = None
            broker = options.get("broker")
            if broker is not None:
                confirm = broker.confirmer(emit)
            return await send(ctx, DeepSeekClient(ctx.config.llm), options.get("request", ""),
                conversation_id=options.get("conversation_id"), want_plan=bool(options.get("want_plan")),
                emit=emit, agent_id=options.get("agent"), confirm=confirm,
                workflow_run_id=options.get("workflow_run_id"), rerun=bool(options.get("rerun")),
                chat_run_id=options.get("chat_run_id"), attachment_paths=options.get("attachment_paths"), control=options.get("control"))
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
        if kind == "benchmark":
            return await check_benchmarks(ctx, emit, options or {})
        if kind == "comments":
            return await collect_comments(ctx, emit, options or {})
        return await analyze(ctx, kind, emit, options or {})
    finally:
        try:
            if ctx.session is not None:
                await ctx.session.stop()
        finally:
            ctx.close()
