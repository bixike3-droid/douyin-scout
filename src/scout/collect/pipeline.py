"""Native collection: own works -> likers -> selected audience samples."""
from __future__ import annotations

import asyncio
import time

from ..store.collection import Coverage, CollectionQueue, Quality
from ..util import iso
from .user_works_api import UserWorksApiCollector
from .likers import LikersCollector


class Pipeline:
    def __init__(self, ctx, emit):
        self.ctx, self.emit = ctx, emit
        self.coverage = Coverage(ctx.db)
        self.queue = CollectionQueue(ctx)
        self.report = {"attempted": 0, "ok": 0, "failed": 0, "partial": 0, "sampled": 0,
                       "cached": 0, "deferred": 0, "requests": 0, "runs": [], "stop_reason": ""}
        self.report["warnings"] = []

    async def _one(self, cls, target, tier, limit, force, hint=""):
        cfg = self.ctx.config.targets
        if not force and self.coverage.fresh(cls.kind, target, required=limit,
                                           ttl_hours=cfg.collection_ttl_hours, hint=hint):
            self.report["cached"] += 1
            self.emit({"message": f"复用已验证缓存：{cls.kind}"})
            return True
        if self.report["attempted"] >= self.budget:
            self.report["stop_reason"] = "达到本轮任务上限，剩余目标保留到下一轮"
            return False
        task = self.queue.claim(cls.kind, target, tier, force=force)
        if task is None:
            self.report["deferred"] += 1
            return True
        self.report["attempted"] += 1
        collector = cls(self.ctx)
        collector.on_progress = self.emit
        try:
            outcome = await collector.run({**task, "_item_limit": limit, "_api_cadence": True,
                                           "_resume": not force, "_hint": hint})
        except asyncio.CancelledError:
            self.queue.release(task)
            raise
        self.report["requests"] += outcome.requests
        entry = outcome.to_dict()
        self.report["runs"].append(entry)
        state = outcome.persisted.get("collection_state")
        if outcome.ok:
            self.ctx.tasks.complete(task["id"])
            self.report["ok"] += 1
            self.report["sampled"] += state == "sampled"
        elif outcome.blocked:
            self.queue.release(task)
            self.report["stop_reason"] = outcome.error
            return False
        else:
            self.report["partial" if state == "partial" else "failed"] += 1
            if outcome.error.startswith("达到页数上限"):
                self.queue.release(task)
            else:
                self.ctx.tasks.fail(task["id"], outcome.error, retry=True)
            if "status_code=8" in outcome.error:
                self.report["stop_reason"] = "登录态失效，请重新登录"
                return False
            if "HTTP 403" in outcome.error:
                self.report["stop_reason"] = outcome.error
                return False
        self.emit({"type": "task", "kind": cls.kind, "ok": outcome.ok, "blocked": outcome.blocked,
                   "attempted": self.report["attempted"], "collection_state": state})
        return True

    async def run(self, *, mode="quick", limit=40, force=False, targets=None, works_limit=None):
        started = time.monotonic()
        self.budget = max(1, int(limit))
        Quality(self.ctx.db).refresh_staleness(self.ctx.config.storage.edge_stale_days)
        owner = self.ctx.cursors.get("self_sec_uid")
        if not owner:
            raise ValueError("尚未确认本人账号，请先登录")
        tier = next(t.name for t in self.ctx.config.tiers.values() if t.enabled and t.mode == "logged_in")
        if targets:
            eligible = {r["sec_uid"] for r in Quality(self.ctx.db).audience()}
            if any(uid not in eligible for uid in targets):
                raise ValueError("所选对象没有当前本人作品的有效互动关联")
            for uid in dict.fromkeys(targets):
                if not await self._one(UserWorksApiCollector, uid, tier,
                    works_limit if works_limit is not None else self.ctx.config.targets.works_per_user_limit, force):
                    break
            return self._finish(started)
        me = self.ctx.users.get(owner) or {}
        hint = f"{me.get('aweme_count')}|{me.get('total_favorited')}"
        self.emit({"message": "正在增量检查自己的作品…"})
        if not await self._one(UserWorksApiCollector, owner, tier, 0, force, hint):
            if "HTTP 403" in self.report["stop_reason"] and self.ctx.works.mine():
                self.report["warnings"].append("本人作品接口暂未刷新，本轮仅处理已有作品，新增作品范围未确认")
                self.report["stop_reason"] = ""
                self.emit({"message": self.report["warnings"][-1]})
            else:
                return self._finish(started)
        own_coverage = self.coverage.get(UserWorksApiCollector.kind, owner)
        if own_coverage and own_coverage["state"] in ("partial", "error") and not self.report["warnings"]:
            self.report["warnings"].append("本人作品列表尚未完整刷新，当前结果基于已知作品")
        self.ctx.works.mark_mine_by_author(owner)
        self.emit({"message": "正在采集作品点赞名单与基础资料…"})
        for work in self.ctx.works.mine():
            if work.get("digg_count") == 0:
                continue
            if not await self._one(LikersCollector, work["aweme_id"], tier, 0, force, str(work.get("digg_count"))):
                break
        if mode == "deep" and not self.report["stop_reason"]:
            quality = Quality(self.ctx.db)
            selected = [r["sec_uid"] for r in quality.audience(repeated_only=True)]
            self.emit({"message": f"正在补充重点互动者作品：候选 {len(selected)} 人"})
            for uid in selected:
                if not await self._one(UserWorksApiCollector, uid, tier,
                                      works_limit if works_limit is not None else self.ctx.config.targets.works_per_user_limit, force):
                    break
        return self._finish(started)

    def _finish(self, started):
        self.report["quality"] = Quality(self.ctx.db).report()
        self.report["duration_s"] = round(time.monotonic() - started, 1)
        self.ctx.db.log_event("info", "pipeline", "采集与质量检查结束", self.report)
        return self.report
