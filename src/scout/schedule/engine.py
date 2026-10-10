"""调度引擎：断点续采 + 配额 + 熔断 的执行者。

一次 run_round 的行为：
1. 先把崩溃遗留的 running 任务捞回来。
2. 按档位轮流领取任务（档 A 优先，因为它配额极小、且是数据发现的源头）。
3. 每个任务都经过采集器模板方法里的护栏。
4. 被护栏拦下 → 该档位本轮停止，原因写进报告（不是失败，是主动停）。
5. 全程可中断：Ctrl+C 后 running 任务会在下次启动时被捞回。

刻意不做的事情：
- 不追求"跑完所有任务"。跑到配额或用完 max_tasks 就停，这是设计而不是缺陷。
- 不做并发。单 IP 低频是长期存活的前提。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..app import AppContext
from ..collect import collector_for
from ..guard.circuit import CircuitOpen
from ..guard.quota import QuotaExceeded
from ..util import iso


@dataclass
class RoundReport:
    started_at: str = field(default_factory=iso)
    finished_at: str = ""
    attempted: int = 0
    ok: int = 0
    empty: int = 0
    failed: int = 0
    blocked: int = 0
    stop_reason: str = ""
    runs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempted": self.attempted,
            "ok": self.ok,
            "empty": self.empty,
            "failed": self.failed,
            "blocked": self.blocked,
            "stop_reason": self.stop_reason,
            "runs": self.runs,
        }


class Engine:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    # ── 种子任务 ────────────────────────────────────────────

    def seed(self) -> dict[str, int]:
        """补齐"该跑的活儿"：互动消息、待办资料、待办作品。

        互动消息用 rearm 而不是 enqueue —— 它是周期任务，
        跑完一次之后下次还要再跑（enqueue 对 done 的任务不生效）。
        """
        ctx = self.ctx
        counts = {"notice": 0, "profile": 0, "works": 0, "likers": 0, "user_works": 0,
                  "self": 0, "stats_refresh": 0, "cleanup": 0}

        notice_url = ctx.config.targets.notice_url
        tier_a = None
        for name, tier in ctx.config.tiers.items():
            if tier.mode == "logged_in" and tier.enabled:
                tier_a = name
                break
        liker_tier = tier_a or "a"

        # 第一步永远是"我是谁"：不知道自己 sec_uid 就没法区分
        # 「我的作品」和「点赞人的作品」，会变成点赞人的点赞人，无限套娃。
        self_uid = ctx.cursors.get("self_sec_uid")
        if not self_uid:
            if ctx.tasks.rearm("fetch_self", "self", liker_tier, priority=5):
                counts["self"] = 1
        else:
            marked = ctx.works.mark_mine_by_author(self_uid)
            if marked:
                ctx.db.log_event("info", "engine", f"标记了 {marked} 个我自己的作品")
        ctx.works.mark_mine()   # 启发式兜底

        if tier_a and notice_url:
            if ctx.tasks.rearm(
                "fetch_notice", notice_url, tier_a,
                min_interval_minutes=ctx.config.targets.notice_min_interval_minutes,
                priority=10,
            ):
                counts["notice"] = 1

        for sec_uid in ctx.users.needs_profile(limit=500):
            if ctx.tasks.enqueue("fetch_profile", sec_uid, "b", priority=50):
                counts["profile"] += 1

        # 有赞的作品 → 拉完整点赞人名单。
        # 这是最关键的一步：接口一次给全 50 人（含完整主页数据），
        # 不需要点任何界面，也不需要挨个访问主页。
        # 注意用档 A：匿名态调这个接口会返回「用户未登录」。
        counts["likers"] = 0
        for aweme_id in ctx.works.need_likers(limit=200):
            if ctx.tasks.enqueue("fetch_likers", aweme_id, liker_tier, priority=30):
                counts["likers"] += 1

        # 点赞人的作品列表 —— AI 画像的原料。
        # 前面两个接口只给了"他是谁"，这个接口给"他发过什么"。
        counts["user_works"] = 0
        for sec_uid in ctx.users.need_works(limit=500):
            if ctx.tasks.enqueue("fetch_user_works", sec_uid, liker_tier, priority=60):
                counts["user_works"] += 1

        # 统计数据保鲜：超过 TTL 的作品重新采一遍。
        # 作品数据是会变的（点赞、评论一直在涨），采一次永不更新
        # 等于在页面上挂一个冻结的数字，而且不告诉用户它是什么时候的。
        counts["stats_refresh"] = 0
        ttl = ctx.config.targets.works_stats_ttl_days
        stale = ctx.works.need_stats_refresh(ttl, limit=ctx.config.targets.works_stats_refresh_limit)
        for sec_uid, _aweme_id in stale:
            # 按作者去重：作品列表接口是按人取的，一个人刷新一次就能覆盖他所有作品
            if ctx.tasks.enqueue("fetch_user_works", sec_uid, liker_tier, priority=80):
                counts["stats_refresh"] += 1

        # ── 保留策略：每天最多自动清理一次 ──
        #
        # 为什么放在 seed 里、又为什么要限"每天一次"：
        # 清理本身很便宜（删文件 + 几条 UPDATE），但它是**破坏性**的。
        # 每轮都跑没必要，而且万一配置写错（比如 raw_days 填了 1），
        # 高频触发会让后果放大得很快。一天一次是安全节奏。
        try:
            from ..store.cleanup import plan_cleanup, run_cleanup

            today = ctx.db.scalar("SELECT date('now')", default="") or ""
            if (
                today
                and ctx.config.storage.raw_retention_days > 0
                and ctx.cursors.get("last_cleanup_day") != today
            ):
                plan = plan_cleanup(ctx)
                if plan.raw_rows or plan.log_rows or plan.task_rows or plan.unconfirmed_edges:
                    res = run_cleanup(ctx, plan, dry_run=False)
                    ctx.cursors.set("last_cleanup_day", today)
                    counts["cleanup"] = res["files_deleted"]
                    ctx.db.log_event(
                        "info", "cleanup",
                        f"自动清理：删 {res['files_deleted']} 个归档文件"
                        f"（{res['bytes_freed'] / 1048576:.1f} MB），"
                        f"标记陈旧点赞边 {res['edges_marked']} 条",
                    )
        except Exception as exc:
            # 清理失败不能影响采集 —— 它只是维护工作
            ctx.db.log_event("warn", "cleanup", f"自动清理失败（不影响采集）：{exc}")

        return counts

    # ── 主循环 ──────────────────────────────────────────────

    async def run_round(
        self,
        *,
        max_tasks: int | None = None,
        tiers: Iterable[str] | None = None,
        kinds: Iterable[str] | None = None,
        dry_run: bool = False,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> RoundReport:
        ctx = self.ctx
        report = RoundReport()
        limit = max_tasks if max_tasks is not None else ctx.config.app.max_tasks_per_run
        wanted_tiers = list(tiers) if tiers else ctx.enabled_tiers()
        wanted_kinds = set(kinds) if kinds else None

        ctx.tasks.reclaim_stuck()
        ctx.cache.purge_expired()

        # 显式指定 kind 时，把该 kind 已结束的任务重新排上。
        # 否则第二次 `scout run --kind fetch_notice` 会什么都不做（任务已是 done）。
        if wanted_kinds:
            rearmed = ctx.tasks.rearm_kinds(sorted(wanted_kinds))
            if rearmed:
                ctx.db.log_event("info", "engine", f"重新排上 {rearmed} 个 {sorted(wanted_kinds)} 任务")

        for tier in wanted_tiers:
            if report.attempted >= limit:
                report.stop_reason = f"达到本轮上限 {limit} 个任务"
                break
            try:
                await self._run_tier(tier, report, limit, wanted_kinds, dry_run, on_event)
            except (QuotaExceeded, CircuitOpen) as exc:
                report.stop_reason = f"[{tier}] {exc}"
                break

        report.finished_at = iso()
        ctx.db.log_event(
            "info",
            "engine",
            f"本轮结束：尝试 {report.attempted}，成功 {report.ok}，空 {report.empty}，"
            f"失败 {report.failed}，被拦 {report.blocked}；{report.stop_reason}",
            report.to_dict()["runs"][:20],
        )
        return report

    async def _run_tier(
        self,
        tier: str,
        report: RoundReport,
        limit: int,
        wanted_kinds: set[str] | None,
        dry_run: bool,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        ctx = self.ctx
        tier_cfg = ctx.tier_cfg(tier)
        idle_streak = 0

        while report.attempted < limit:
            # 档位护栏：任何一项不过就整档停下
            ctx.guard(tier)

            tasks = ctx.tasks.claim(tier, limit=1, kinds=sorted(wanted_kinds) if wanted_kinds else None)
            if not tasks:
                idle_streak += 1
                if idle_streak >= 2:
                    return
                continue
            idle_streak = 0

            task = tasks[0]

            collector_cls = collector_for(task["kind"])
            if collector_cls is None:
                ctx.tasks.fail(task["id"], f"没有 kind={task['kind']} 的采集器", retry=False)
                report.failed += 1
                report.attempted += 1
                continue

            report.attempted += 1
            if dry_run:
                report.runs.append({
                    "kind": task["kind"],
                    "tier": tier,
                    "target": task["target"],
                    "dry_run": True,
                    "ok": True,
                    "empty": False,
                    "captured": 0,
                    "persisted": {"dry_run": True},
                })
                ctx.tasks.complete(task["id"])
                continue

            collector = collector_cls(ctx)
            outcome = await collector.run(task)
            entry = outcome.to_dict()
            entry["task_id"] = task["id"]
            report.runs.append(entry)

            # 进度回调：网页要实时看到"正在跑哪个、跑到第几个"。
            # 放在这里而不是每个采集器里，是因为这是唯一知道
            # "刚刚完成了什么"的地方，采集器本身不该关心谁来订阅。
            if on_event is not None:
                try:
                    on_event({
                        "type": "task",
                        "tier": tier,
                        "kind": task["kind"],
                        "target": task["target"],
                        "ok": outcome.ok,
                        "empty": outcome.empty,
                        "blocked": outcome.blocked,
                        "captured": outcome.captured,
                        "parsed": outcome.parsed.summary() if outcome.parsed else "",
                        "duration_ms": outcome.duration_ms,
                        "error": outcome.error,
                        "attempted": report.attempted,
                        "limit": limit,
                    })
                except Exception:
                    pass   # 回调出错不能影响采集本身

            if outcome.blocked:
                report.blocked += 1
                # 护栏拦下：任务放回 pending，不计失败、不消耗重试次数
                ctx.db.execute(
                    "UPDATE tasks SET state='pending', claimed_at=NULL, attempts=MAX(attempts-1,0) "
                    "WHERE id=?",
                    (task["id"],),
                )
                if "配额" in (outcome.error or ""):
                    raise QuotaExceeded(tier, ctx.quota.used(tier), ctx.quota.limit(tier))
                raise CircuitOpen(tier, outcome.error or "熔断", None)

            if outcome.ok:
                report.ok += 1
                ctx.tasks.complete(task["id"])
            elif outcome.empty:
                report.empty += 1
                # 空返回不重试太多次：可能只是这个用户被限制或主页不存在
                ctx.tasks.fail(task["id"], outcome.error or "空返回", retry=True)
            else:
                report.failed += 1
                ctx.tasks.fail(task["id"], outcome.error or "未知错误", retry=True)

        if report.attempted >= limit:
            report.stop_reason = f"达到本轮上限 {limit} 个任务"
