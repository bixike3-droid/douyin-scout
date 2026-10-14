"""应用上下文：把配置、存储、护栏、会话组装成一个可用的整体。

所有命令都通过 AppContext.create() 拿到一个装配好的上下文，
不在各处零散地 new 对象。这样依赖关系只有一处，测试也好替换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Config, load_config
from .db.connect import Database
from .db.migrate import migrate
from .guard.circuit import CircuitBreaker
from .guard.quota import QuotaManager
from .guard.throttle import Throttle
from .paths import Paths
from .store.cache import AbstractCache, make_cache
from .store.raw_archive import RawArchive
from .store.repo import (
    Cursors,
    LikeEdges,
    LLMResults,
    NoticeRuns,
    Tasks,
    UserSnapshots,
    Users,
    Works,
)
from .store.telemetry import Telemetry


@dataclass
class AppContext:
    config: Config
    paths: Paths
    db: Database
    archive: RawArchive
    cache: AbstractCache
    users: Users
    works: Works
    like_edges: LikeEdges
    snapshots: UserSnapshots
    notice_runs: NoticeRuns
    llm_results: LLMResults
    tasks: Tasks
    cursors: Cursors
    telemetry: Telemetry
    quota: QuotaManager
    circuit: CircuitBreaker
    throttle: Throttle
    session: Any = None  # SessionManager，按需注入（避免核心模块依赖 playwright）

    # ── 构造 ────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        config: Config | None = None,
        *,
        migrate_db: bool = True,
        cache_backend: str = "sqlite",
    ) -> "AppContext":
        cfg = config or load_config()
        cfg.paths.ensure()
        db = Database.open(cfg.paths.db_path)
        if migrate_db:
            migrate(db)

        tel = Telemetry(db, tz=cfg.app.timezone)
        limits = {name: tier.daily_request_quota for name, tier in cfg.tiers.items()}

        return cls(
            config=cfg,
            paths=cfg.paths,
            db=db,
            archive=RawArchive(db, cfg.paths, max_bytes=cfg.storage.raw_max_bytes),
            cache=make_cache(db, cache_backend),
            users=Users(db),
            works=Works(db),
            like_edges=LikeEdges(db),
            snapshots=UserSnapshots(db),
            notice_runs=NoticeRuns(db),
            llm_results=LLMResults(db),
            tasks=Tasks(db, cfg.guard.backoff),
            cursors=Cursors(db),
            telemetry=tel,
            quota=QuotaManager(tel, limits),
            circuit=CircuitBreaker(tel, cfg.guard.circuit),
            throttle=Throttle(cfg.guard.throttle),
        )

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "AppContext":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── 会话 ────────────────────────────────────────────────

    async def open_session(self, *, headless_override: bool | None = None) -> Any:
        from .session.manager import SessionManager

        if self.session is None:
            manager = SessionManager(
                self.config, headless_override=headless_override
            )
            try:
                await manager.start()
            except BaseException:
                await manager.stop()
                raise
            self.session = manager
        return self.session

    # ── 护栏 ────────────────────────────────────────────────

    def guard(self, tier: str) -> None:
        """发请求前的总闸。任一不过就抛异常。"""
        self.circuit.check(tier)
        self.quota.check(tier)

    def tier_cfg(self, tier: str):
        return self.config.tier(tier)

    def enabled_tiers(self) -> list[str]:
        return self.config.enabled_tiers()

    def snapshot(self) -> dict[str, Any]:
        return {
            "tiers": {
                name: {
                    "enabled": t.enabled,
                    "mode": t.mode,
                    "headless": t.headless,
                    "min_delay_s": t.min_delay_s,
                    "max_delay_s": t.max_delay_s,
                    "quota": t.daily_request_quota,
                }
                for name, t in sorted(self.config.tiers.items())
            },
            "config_sources": list(self.config.sources),
            "targets": {
                "home_url": self.config.targets.home_url,
                "notice_url": self.config.targets.notice_url,
                "user_url_template": self.config.targets.user_url_template,
            },
            "guard_circuit": {
                "consecutive_empty_open": self.config.guard.circuit.consecutive_empty_open,
                "consecutive_error_open": self.config.guard.circuit.consecutive_error_open,
                "cooldown_minutes": self.config.guard.circuit.cooldown_minutes,
            },
            "session": self.session.stats() if self.session else None,
        }
