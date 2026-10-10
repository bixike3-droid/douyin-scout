"""本地网页面板。

定位：**只读观测台**。看数据、看配额、看熔断、看请求日志，不在这里改配置、
也不在这里启动采集——那种事走 CLI，避免浏览器里误触就发出一堆请求。

日志用 SSE 推送（比 WebSocket 简单，够用，断线浏览器会自动重连）。
每个请求开一个只读连接：FastAPI 会把同步端点丢到线程池，共享连接会出问题。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from ..analyze import analyze_users, overview, render_markdown
from ..config import load_config
from ..db.connect import Database
from ..paths import Paths
from ..util import iso, truncate

STATIC_DIR = Path(__file__).parent / "static"
SSE_INTERVAL_S = 3.0


class _ReadOnly:
    """按请求开只读连接。数据库不存在时返回 None，由端点给出友好提示。"""

    def __init__(self) -> None:
        self.paths = Paths.build()

    def open(self) -> Database | None:
        if not self.paths.db_path.exists():
            return None
        return Database.open(self.paths.db_path, read_only=True)


def create_app() -> FastAPI:
    app = FastAPI(title="douyin-scout", docs_url="/api/docs", redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    def _store() -> _ReadOnly:
        return _ReadOnly()

    @app.get("/api/overview")
    def api_overview() -> JSONResponse:
        ro = _store()
        db = ro.open()
        if db is None:
            return JSONResponse({"error": "数据库不存在，请先运行 scout init"}, status_code=503)
        try:
            from ..app import AppContext

            ctx = AppContext.create(migrate_db=False)
            try:
                data = overview(ctx)
                data["paths"] = {"db": str(ro.paths.db_path), "raw": str(ro.paths.raw_dir)}
                return JSONResponse(data)
            finally:
                ctx.close()
        finally:
            db.close()

    @app.get("/api/config")
    def api_config() -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse(ctx.snapshot())
        finally:
            ctx.close()

    @app.get("/api/users")
    def api_users(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        order: str = Query("like_count"),
        state: str = Query(""),
    ) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            rows = ctx.users.list(limit=limit, offset=offset, order=order, state=state or None)
            return JSONResponse(rows)
        finally:
            ctx.close()

    @app.get("/api/works")
    def api_works(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        mine_only: bool = Query(False),
    ) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse(ctx.works.list(limit=limit, offset=offset, mine_only=mine_only))
        finally:
            ctx.close()

    @app.get("/api/likers")
    def api_likers(limit: int = Query(30, ge=1, le=200)) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse(ctx.like_edges.top_likers(limit=limit))
        finally:
            ctx.close()

    @app.get("/api/likers/detail")
    def api_likers_detail(
        work: str = Query("", help="只看某个作品的点赞人"),
        q: str = Query("", help="按昵称或抖音号搜索"),
        limit: int = Query(300, ge=1, le=2000),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """点赞人档案：每个人带完整主页字段，可直接拼出抖音主页地址。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            where, params = [], []
            if work:
                where.append("le.aweme_id = ?")
                params.append(work)
            if q:
                where.append("(u.nickname LIKE ? OR u.douyin_id LIKE ?)")
                params += [f"%{q}%", f"%{q}%"]
            clause = ("WHERE " + " AND ".join(where)) if where else ""
            sql = f"""
                SELECT
                    u.sec_uid, u.nickname, u.douyin_id, u.signature, u.avatar_url,
                    u.follower_count, u.following_count, u.aweme_count,
                    u.total_favorited, u.region, u.is_verified, u.verification,
                    le.aweme_id, le.notice_id, le.merge_count, le.notice_kind,
                    le.discovered_at,
                    'https://www.douyin.com/user/' || u.sec_uid AS profile_url
                FROM users u
                JOIN like_edges le ON le.sec_uid = u.sec_uid
                {clause}
                ORDER BY COALESCE(u.follower_count, -1) DESC, u.nickname
                LIMIT ? OFFSET ?
            """
            params += [limit, offset]
            rows = ctx.db.rows_as_dicts(sql, params)
            total = ctx.db.scalar(
                f"SELECT COUNT(*) FROM users u JOIN like_edges le ON le.sec_uid = u.sec_uid {clause}",
                params[:-2],
                default=0,
            )
            return JSONResponse({"total": total, "returned": len(rows), "rows": rows})
        finally:
            ctx.close()

    @app.get("/api/user_works")
    def api_user_works(
        sec_uid: str = Query("", help="只看某个点赞人的作品"),
        q: str = Query("", help="按标题搜索"),
        limit: int = Query(300, ge=1, le=2000),
        offset: int = Query(0, ge=0),
    ) -> JSONResponse:
        """点赞人的作品列表 —— AI 画像的原料。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            where, params = ["1=1"], []
            if sec_uid:
                where.append("l.sec_uid = ?")
                params.append(sec_uid)
            if q:
                where.append("w.description LIKE ?")
                params.append(f"%{q}%")
            clause = " AND ".join(where)
            rows = ctx.db.rows_as_dicts(
                f"""
                SELECT w.aweme_id, w.description, w.digg_count, w.comment_count,
                       w.share_count, w.create_time, w.duration_ms, w.music_title,
                       w.cover_url, w.hashtags_json,
                       w.stats_fetched_at, w.stats_anomaly, w.raw_blob_id,
                       l.sec_uid, u.nickname AS author_nickname,
                       u.douyin_id AS author_douyin_id, u.follower_count AS author_fans,
                       'https://www.douyin.com/user/' || l.sec_uid AS author_url
                FROM user_work_listings l
                JOIN works w ON w.aweme_id = l.aweme_id
                LEFT JOIN users u ON u.sec_uid = l.sec_uid
                WHERE {clause}
                ORDER BY COALESCE(w.digg_count, -1) DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            # 时效：让页面能显示"这些数字是什么时候采的"，
            # 而不是把一个可能过期的数字当成当前事实。
            import time as _time

            now = _time.time()
            ttl_days = ctx.config.targets.works_stats_ttl_days
            for r in rows:
                stamp = r.get("stats_fetched_at") or ""
                age_h = None
                if stamp:
                    try:
                        from datetime import datetime, timezone

                        dt = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=timezone.utc
                        )
                        age_h = (now - dt.timestamp()) / 3600
                    except Exception:
                        age_h = None
                r["stats_age_hours"] = round(age_h, 1) if age_h is not None else None
                r["stats_stale"] = bool(age_h is not None and age_h > ttl_days * 24)
                r["stats_unknown_time"] = age_h is None
            total = ctx.db.scalar(
                f"SELECT COUNT(*) FROM user_work_listings l JOIN works w ON w.aweme_id=l.aweme_id WHERE {clause}",
                params,
                default=0,
            )
            return JSONResponse({"total": total, "returned": len(rows), "rows": rows})
        finally:
            ctx.close()

    @app.get("/api/likers/summary")
    def api_likers_summary() -> JSONResponse:
        """每个点赞人采到了几个作品 —— 用来判断画像原料够不够。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            rows = ctx.db.rows_as_dicts(
                """
                SELECT u.sec_uid, u.nickname, u.douyin_id, u.follower_count, u.signature,
                       COUNT(l.aweme_id) AS works_have,
                       'https://www.douyin.com/user/' || u.sec_uid AS profile_url
                FROM users u
                LEFT JOIN user_work_listings l ON l.sec_uid = u.sec_uid
                WHERE u.sec_uid IN (SELECT sec_uid FROM like_edges)
                GROUP BY u.sec_uid
                ORDER BY works_have DESC, COALESCE(u.follower_count, -1) DESC
                """
            )
            return JSONResponse(rows)
        finally:
            ctx.close()

    @app.get("/api/works/overview")
    def api_works_overview() -> JSONResponse:
        """我的作品 + 每个作品拿到了多少点赞人。用来核对"是不是拿全了"。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            rows = ctx.db.rows_as_dicts(
                """
                SELECT
                    w.aweme_id, w.description, w.digg_count, w.create_time, w.cover_url,
                    (SELECT COUNT(DISTINCT le.sec_uid) FROM like_edges le
                     WHERE le.aweme_id = w.aweme_id) AS likers_have,
                    (SELECT COUNT(*) FROM like_edges le
                     WHERE le.aweme_id = w.aweme_id AND le.notice_id LIKE 'api:%') AS from_api
                FROM works w
                WHERE w.is_mine = 1 AND COALESCE(w.digg_count, 0) > 0
                ORDER BY w.digg_count DESC
                """
            )
            for r in rows:
                have = int(r.get("likers_have") or 0)
                stated = int(r.get("digg_count") or 0)
                r["complete"] = bool(r.get("from_api")) and have >= stated
                r["gap"] = max(0, stated - have)
            return JSONResponse(rows)
        finally:
            ctx.close()

    @app.post("/api/works/{aweme_id}/fetch_likers")
    def api_fetch_likers(aweme_id: str) -> JSONResponse:
        """把某个作品的点赞人采集任务排进队列（面板上点一下就触发）。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            ok = ctx.tasks.enqueue("fetch_likers", aweme_id, "a", priority=20)
            ctx.db.log_event("info", "web", f"面板请求采集点赞人：{aweme_id}")
            return JSONResponse({"queued": bool(ok), "aweme_id": aweme_id})
        finally:
            ctx.close()

    @app.get("/api/tasks")
    def api_tasks(limit: int = Query(50, ge=1, le=500), state: str = Query("")) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse(ctx.tasks.list(limit=limit, state=state or None))
        finally:
            ctx.close()

    @app.get("/api/requests")
    def api_requests(
        limit: int = Query(80, ge=1, le=500),
        tier: str = Query(""),
        only_problem: bool = Query(False),
    ) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            rows = ctx.telemetry.recent_requests(
                limit=limit, tier=tier or None, only_problem=only_problem
            )
            return JSONResponse(rows)
        finally:
            ctx.close()

    @app.get("/api/raw")
    def api_raw(limit: int = Query(40, ge=1, le=200)) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse(ctx.archive.recent(limit))
        finally:
            ctx.close()

    @app.get("/api/coverage")
    def api_coverage() -> JSONResponse:
        """名单完整性证据：触底判定 + 历史采集轮次。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse({
                "coverage": ctx.notice_runs.coverage(),
                "runs": ctx.notice_runs.recent(limit=30),
            })
        finally:
            ctx.close()

    # ── AI 画像 ─────────────────────────────────────────────

    # ── 采集控制 ────────────────────────────────────────────
    #
    # 原来是"网页只读、采集走 CLI"。对比赛作品来说，
    # "必须去终端敲命令"是不合格的。这里让网页直接能干活。

    @app.post("/api/collect/start")
    async def api_collect_start(
        kinds: str = Query("", description="只跑某类任务，逗号分隔，留空=全部"),
        max_tasks: int = Query(0, ge=0, le=500, description="本轮最多几个任务，0=用配置值"),
    ) -> JSONResponse:
        from .runner import CollectionRunner

        runner = CollectionRunner.get()
        result = await runner.start(kinds=kinds, max_tasks=max_tasks)
        return JSONResponse(result, status_code=200 if result.get("accepted") else 409)

    @app.post("/api/collect/stop")
    async def api_collect_stop() -> JSONResponse:
        from .runner import CollectionRunner

        return JSONResponse(await CollectionRunner.get().stop())

    @app.get("/api/collect/status")
    def api_collect_status() -> JSONResponse:
        from .runner import CollectionRunner

        runner = CollectionRunner.get()
        return JSONResponse({
            "busy": runner.busy,
            "state": runner.state.to_dict(),
            "events": len(runner._history),
        })

    @app.get("/api/collect/stream")
    async def api_collect_stream() -> StreamingResponse:
        """SSE：采集进度。

        先回放已经发生的事件（用户可能在采集跑到一半时才打开页面），
        再实时推送新的。
        """
        from .runner import CollectionRunner

        runner = CollectionRunner.get()

        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"

        async def gen() -> AsyncIterator[str]:
            queue, replay = runner.subscribe()
            try:
                yield sse({"type": "snapshot", "busy": runner.busy,
                           "state": runner.state.to_dict()})
                for ev in replay:
                    yield sse(ev)
                # 队列还没关，就保持连接；空闲时发心跳防止代理断链
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield sse(ev)
            finally:
                runner.unsubscribe(queue)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/tasks/summary")
    def api_tasks_summary() -> JSONResponse:
        """按类型统计待办 —— 界面上让用户知道"点下去会发生什么"。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            rows = ctx.db.rows_as_dicts(
                "SELECT kind, state, COUNT(*) AS n FROM tasks GROUP BY kind, state"
            )
            by_kind: dict[str, dict[str, int]] = {}
            for r in rows:
                by_kind.setdefault(r["kind"], {})[r["state"]] = r["n"]
            kinds = [
                {"kind": k, "pending": v.get("pending", 0) + v.get("running", 0),
                 "done": v.get("done", 0), "failed": v.get("failed", 0)}
                for k, v in sorted(by_kind.items())
            ]
            for item in kinds:
                item["ready"] = item["pending"]
            return JSONResponse({
                "kinds": kinds,
                "totals": ctx.tasks.stats(),
            })
        finally:
            ctx.close()

    @app.get("/api/storage")
    def api_storage() -> JSONResponse:
        """归档现状 + 清理预览。让用户看到"还能撑多久"。"""
        from ..app import AppContext
        from ..store.cleanup import archive_stats, plan_cleanup

        ctx = AppContext.create(migrate_db=False)
        try:
            stats = archive_stats(ctx)
            plan = plan_cleanup(ctx)
            return JSONResponse({
                "archive": stats,
                "plan": plan.to_dict(),
                "thresholds": {
                    "raw_retention_days": ctx.config.storage.raw_retention_days,
                    "log_retention_days": ctx.config.storage.log_retention_days,
                    "task_retention_days": ctx.config.storage.task_retention_days,
                    "edge_stale_days": ctx.config.storage.edge_stale_days,
                },
            })
        finally:
            ctx.close()

    @app.post("/api/storage/cleanup")
    def api_storage_cleanup() -> JSONResponse:
        """执行一次清理（删归档正文、清日志、标记陈旧边）。

        对比赛作品来说，清理不该只在命令行里做 ——
        但它是破坏性的，所以接口只做"按当前策略执行"，不接受临时改阈值。
        """
        from ..app import AppContext
        from ..store.cleanup import plan_cleanup, run_cleanup

        ctx = AppContext.create(migrate_db=False)
        try:
            plan = plan_cleanup(ctx)
            if not (plan.raw_rows or plan.log_rows or plan.task_rows or plan.unconfirmed_edges):
                return JSONResponse({"cleaned": False, "reason": "没有需要清理的内容"})
            result = run_cleanup(ctx, plan, dry_run=False)
            ctx.db.log_event(
                "info", "cleanup",
                f"网页触发清理：删 {result['files_deleted']} 个文件，"
                f"释放 {result['bytes_freed'] / 1048576:.1f} MB",
            )
            return JSONResponse({"cleaned": True, **result})
        finally:
            ctx.close()

    @app.get("/api/account")
    def api_account() -> JSONResponse:
        """当前用的是哪个账号的数据目录 —— 页面上必须能一眼看到。

        看不到就会发生这种事：以为自己在看 A 号的数据，其实是 B 号的。
        """
        from ..app import AppContext
        from ..store.account import stored_identity

        ctx = AppContext.create(migrate_db=False)
        try:
            sec, nick = stored_identity(ctx)
            paths = ctx.paths
            return JSONResponse({
                "account": paths.account,
                "data_dir": str(paths.data_dir),
                "db_path": str(paths.db_path),
                "all_accounts": paths.list_accounts(),
                "self_sec_uid": sec,
                "self_nickname": nick,
            })
        finally:
            ctx.close()

    @app.get("/api/llm/status")
    async def api_llm_status(ping: bool = Query(False)) -> JSONResponse:
        """大模型配置与连通性。"""
        from ..app import AppContext
        from ..llm import DeepSeekClient, LLMError

        ctx = AppContext.create(migrate_db=False)
        try:
            cfg = ctx.config.llm
            out: dict = {
                "enabled": cfg.enabled,
                "model": cfg.model,
                "base_url": cfg.base_url,
                "api_key_masked": (cfg.api_key[:8] + "…" + cfg.api_key[-4:]) if cfg.api_key else "",
                "usage": ctx.llm_results.stats(),
            }
            if ping and cfg.enabled:
                try:
                    out["ping"] = await DeepSeekClient(cfg).ping()
                except LLMError as exc:
                    out["ping"] = {"ok": False, "error": str(exc)}
            return JSONResponse(out)
        finally:
            ctx.close()

    @app.get("/api/creator")
    def api_creator() -> JSONResponse:
        """作品评价 + 下一步计划（各取最新一次）。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            out: dict = {}
            for task in ("review", "plan"):
                r = ctx.llm_results.latest("self", "me", task)
                out[task] = (
                    {
                        "output_json": r["output_json"],
                        "created_at": r["created_at"],
                        "model": r["model"],
                        "prompt_version": r["prompt_version"],
                        "tokens": (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0),
                    }
                    if r
                    else None
                )
            return JSONResponse(out)
        finally:
            ctx.close()

    @app.get("/api/creator/stream")
    async def api_creator_stream(
        task: str = Query("review", description="review=评价我的作品；plan=下一步计划"),
        force: bool = Query(False),
    ) -> StreamingResponse:
        """SSE：跑创作者侧分析。单次调用要十几秒，必须流式。"""
        from ..analyze.creator import analyze_plan, analyze_review
        from ..app import AppContext
        from ..llm import DeepSeekClient

        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"

        async def gen() -> AsyncIterator[str]:
            ctx = AppContext.create(migrate_db=False)
            try:
                if not ctx.config.llm.enabled:
                    yield sse({"type": "error", "error": "没有配置 DeepSeek api_key"})
                    return
                client = DeepSeekClient(ctx.config.llm)
                yield sse({"type": "start", "task": task})
                result = (
                    await analyze_plan(ctx, client, force=force)
                    if task == "plan"
                    else await analyze_review(ctx, client, force=force)
                )
                yield sse({"type": "result", "task": task, **result.to_dict()})
                yield sse({"type": "done"})
            except Exception as exc:
                yield sse({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            finally:
                ctx.close()

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/analyses")
    def api_analyses() -> JSONResponse:
        """已生成的画像（每人取最新一次），拼上用户资料供页面渲染。"""
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            rows = ctx.db.rows_as_dicts(
                """
                SELECT r.subject_id AS sec_uid, r.subject_kind, r.task,
                       r.prompt_version, r.model, r.output_json, r.created_at,
                       r.prompt_tokens, r.completion_tokens, r.duration_ms,
                       r.input_summary,
                       u.nickname, u.douyin_id, u.follower_count, u.avatar_url,
                       u.signature,
                       'https://www.douyin.com/user/' || u.sec_uid AS profile_url
                FROM v_llm_latest r
                LEFT JOIN users u ON u.sec_uid = r.subject_id
                WHERE r.task = 'profile' AND r.subject_kind = 'user'
                ORDER BY r.created_at DESC
                """
            )
            return JSONResponse(rows)
        finally:
            ctx.close()

    @app.get("/api/analyze/stream")
    async def api_analyze_stream(
        scope: str = Query("pending", description="pending=只分析没分析过的；all=全部重跑"),
        limit: int = Query(30, ge=1, le=200),
        force: bool = Query(False),
    ) -> StreamingResponse:
        """SSE：逐个分析并实时推送结果。

        为什么要流式：一次分析几秒，几十个人就是几分钟。
        轮询式的 POST 会超时，页面也看不到进度。
        """
        import asyncio

        from ..analyze.ai import analyze_many, pending_targets
        from ..app import AppContext
        from ..llm import DeepSeekClient

        def sse(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"

        async def gen() -> AsyncIterator[str]:
            ctx = AppContext.create(migrate_db=False)
            try:
                if not ctx.config.llm.enabled:
                    yield sse({
                        "type": "error",
                        "error": "没有配置 DeepSeek api_key。请填 config/llm.local.yaml 的 llm.api_key",
                    })
                    return

                if scope == "all":
                    targets = [
                        r["sec_uid"] for r in ctx.db.query(
                            "SELECT DISTINCT sec_uid FROM like_edges LIMIT ?", (limit,)
                        )
                    ]
                else:
                    targets = pending_targets(ctx, force=False, limit=limit)

                if not targets:
                    yield sse({"type": "done", "total": 0, "ok": 0, "failed": 0,
                               "message": "没有需要分析的对象（都分析过了；要重跑选「全部重跑」）"})
                    return

                yield sse({"type": "start", "total": len(targets)})

                queue: asyncio.Queue = asyncio.Queue()
                client = DeepSeekClient(ctx.config.llm)

                def on_progress(event: dict) -> None:
                    queue.put_nowait(event)

                task = asyncio.create_task(
                    analyze_many(ctx, client, targets, force=force, on_progress=on_progress)
                )
                try:
                    while True:
                        try:
                            event = await asyncio.wait_for(queue.get(), timeout=1.0)
                        except asyncio.TimeoutError:
                            if task.done() and queue.empty():
                                break
                            yield ": keepalive\n\n"
                            continue
                        yield sse(event)
                        if event.get("type") == "done":
                            break
                finally:
                    if not task.done():
                        task.cancel()
                    else:
                        exc = task.exception() if not task.cancelled() else None
                        if exc:
                            yield sse({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            except Exception as exc:
                yield sse({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
            finally:
                ctx.close()

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/events")
    def api_events(limit: int = Query(60, ge=1, le=300), level: str = Query("")) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            return JSONResponse(ctx.telemetry.events(limit=limit, level=level or None))
        finally:
            ctx.close()

    @app.get("/api/report")
    def api_report() -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            data = analyze_users(ctx)
            return JSONResponse({"data": data, "markdown": render_markdown(data)})
        finally:
            ctx.close()

    @app.post("/api/circuit/{tier}/reset")
    def api_circuit_reset(tier: str) -> JSONResponse:
        from ..app import AppContext

        ctx = AppContext.create(migrate_db=False)
        try:
            ctx.circuit.reset(tier)
            ctx.db.log_event("info", "web", f"人工重置熔断：{tier}")
            return JSONResponse({"ok": True, "tier": tier, "state": "closed"})
        finally:
            ctx.close()

    @app.get("/api/stream")
    async def api_stream() -> StreamingResponse:
        """SSE：周期性推送概览 + 新事件。前端断线会自动重连。"""

        async def gen() -> AsyncIterator[str]:
            last_event_id = 0
            while True:
                payload: dict[str, Any] = {"ts": iso()}
                try:
                    from ..app import AppContext

                    ctx = AppContext.create(migrate_db=False)
                    try:
                        payload["overview"] = overview(ctx)
                        rows = ctx.telemetry.events(limit=20)
                        fresh = [r for r in rows if int(r["id"]) > last_event_id]
                        if fresh:
                            last_event_id = max(int(r["id"]) for r in fresh)
                        payload["events"] = fresh
                    finally:
                        ctx.close()
                except Exception as exc:
                    payload["error"] = truncate(str(exc), 300)
                yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                await asyncio.sleep(SSE_INTERVAL_S)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
