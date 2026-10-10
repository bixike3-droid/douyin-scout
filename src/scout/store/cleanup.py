"""数据保留与清理。

**为什么要有这个模块**

查了一遍数据生命周期，发现四件事都没有处理：

1. **归档只增不减** —— `raw/` 下每天一个目录，正文很快堆到几个 GB
2. **日志只增不减** —— `request_logs` / `event_logs` 每来一个请求加一行
3. **撤销了的数据不会被标记** —— 有人取消点赞，`like_edges` 里那条还在，
   数据会慢慢偏离现实，而且**从外表完全看不出来**
4. **任务表只增不减** —— `done` 的任务永远留着

**三条设计取舍**（都是"宁可保守"）

- **删正文，保留元数据。** `raw_blobs` 只占几 MB，`raw/` 正文占几十 MB。
  留下 sha256/url/byte_size/collected_at，"曾经采过什么"仍可追溯，
  代价只有几字节。直接删 raw_blobs 行会让 `works.raw_blob_id` 变悬空引用。
- **陈旧的点赞边只标记，不删除。** 可能是接口偶发返回不全，
  删了就找不回来。标记成 `is_stale`，让上层自己决定怎么用。
- **必须先能预览。** 破坏性操作一律支持 dry-run。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..app import AppContext


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(0, days))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass
class CleanupPlan:
    """清理计划 —— 先算清楚要动什么，再决定动不动手。"""

    raw_rows: int = 0
    raw_files: int = 0
    raw_bytes: int = 0
    raw_dirs: list[str] = field(default_factory=list)

    log_rows: dict[str, int] = field(default_factory=dict)
    task_rows: int = 0
    stale_edges: int = 0
    unconfirmed_edges: int = 0

    thresholds: dict[str, int] = field(default_factory=dict)

    @property
    def total_bytes(self) -> int:
        return self.raw_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_rows": self.raw_rows,
            "raw_files": self.raw_files,
            "raw_bytes": self.raw_bytes,
            "raw_mb": round(self.raw_bytes / 1048576, 2),
            "raw_dirs": self.raw_dirs,
            "log_rows": self.log_rows,
            "task_rows": self.task_rows,
            "stale_edges": self.stale_edges,
            "unconfirmed_edges": self.unconfirmed_edges,
            "thresholds": self.thresholds,
        }


def _thresholds(ctx: AppContext, overrides: dict[str, int] | None = None) -> dict[str, int]:
    s = ctx.config.storage
    out = {
        "raw_days": s.raw_retention_days,
        "log_days": s.log_retention_days,
        "task_days": s.task_retention_days,
        "edge_days": s.edge_stale_days,
    }
    for k, v in (overrides or {}).items():
        if v is not None:
            out[k] = int(v)
    return out


def plan_cleanup(ctx: AppContext, **overrides: int) -> CleanupPlan:
    """算一遍"按当前策略要清什么"，什么都不改。"""
    th = _thresholds(ctx, overrides)
    plan = CleanupPlan(thresholds=th)

    # ① 归档正文（优先级最高：占空间的大头）
    if th["raw_days"] > 0:
        cutoff = _cutoff(th["raw_days"])
        rows = ctx.db.rows_as_dicts(
            "SELECT id, path, byte_size FROM raw_blobs "
            "WHERE collected_at < ? AND (pruned_at IS NULL OR pruned_at = '')",
            (cutoff,),
        )
        plan.raw_rows = len(rows)
        dirs: set[str] = set()
        for r in rows:
            rel = r.get("path") or ""
            if not rel:
                continue
            try:
                target = ctx.paths.root / rel
                if target.is_file():
                    plan.raw_files += 1
                    plan.raw_bytes += int(r.get("byte_size") or 0)
                dirs.add(str(Path(rel).parent))
            except Exception:
                pass
        plan.raw_dirs = sorted(dirs)

    # ② 日志表
    if th["log_days"] > 0:
        cutoff = _cutoff(th["log_days"])
        for table, col in (("request_logs", "ts"), ("event_logs", "ts")):
            n = ctx.db.scalar(
                f"SELECT COUNT(*) FROM {table} WHERE {col} < ?", (cutoff,), default=0
            )
            if n:
                plan.log_rows[table] = int(n)

    # ③ 陈旧点赞边（只标记不删）
    if th["edge_days"] > 0:
        cutoff = _cutoff(th["edge_days"])
        plan.unconfirmed_edges = int(
            ctx.db.scalar(
                "SELECT COUNT(*) FROM like_edges "
                "WHERE (last_confirmed_at = '' OR last_confirmed_at < ?) AND is_stale = 0",
                (cutoff,),
                default=0,
            )
        )
        plan.stale_edges = int(
            ctx.db.scalar("SELECT COUNT(*) FROM like_edges WHERE is_stale = 1", default=0)
        )

    # ④ 已完成任务
    if th["task_days"] > 0:
        cutoff = _cutoff(th["task_days"])
        plan.task_rows = int(
            ctx.db.scalar(
                "SELECT COUNT(*) FROM tasks WHERE state = 'done' "
                "AND COALESCE(finished_at, updated_at) < ?",
                (cutoff,),
                default=0,
            )
        )

    return plan


def run_cleanup(ctx: AppContext, plan: CleanupPlan, *, dry_run: bool = True) -> dict[str, Any]:
    """执行清理计划。dry_run=True 时只报告不动手。"""
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "files_deleted": 0,
        "bytes_freed": 0,
        "raw_marked": 0,
        "logs_deleted": {},
        "edges_marked": 0,
        "tasks_deleted": 0,
        "errors": [],
    }
    th = plan.thresholds

    # ① 删正文，但**保留 raw_blobs 元数据行**
    if th["raw_days"] > 0 and plan.raw_rows:
        cutoff = _cutoff(th["raw_days"])
        rows = ctx.db.rows_as_dicts(
            "SELECT id, path, byte_size FROM raw_blobs "
            "WHERE collected_at < ? AND (pruned_at IS NULL OR pruned_at = '')",
            (cutoff,),
        )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for r in rows:
            rel = r.get("path") or ""
            size = int(r.get("byte_size") or 0)
            if rel:
                try:
                    target = ctx.paths.root / rel
                    if target.is_file():
                        if not dry_run:
                            target.unlink()
                        result["files_deleted"] += 1
                        result["bytes_freed"] += size
                except Exception as exc:
                    result["errors"].append(f"{rel}: {exc}")
            if not dry_run:
                ctx.db.execute(
                    "UPDATE raw_blobs SET pruned_at = ?, pruned_bytes = ?, path = '' WHERE id = ?",
                    (now, size, r["id"]),
                )
            result["raw_marked"] += 1

        # 顺手把空的日期目录删掉
        if not dry_run:
            for rel_dir in plan.raw_dirs:
                try:
                    d = ctx.paths.root / rel_dir
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                except Exception:
                    pass

    # ② 日志
    if th["log_days"] > 0:
        cutoff = _cutoff(th["log_days"])
        for table, col in (("request_logs", "ts"), ("event_logs", "ts")):
            n = plan.log_rows.get(table, 0)
            if n and not dry_run:
                ctx.db.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
            result["logs_deleted"][table] = n

    # ③ 陈旧点赞边 —— 只标记
    if th["edge_days"] > 0 and plan.unconfirmed_edges:
        cutoff = _cutoff(th["edge_days"])
        if not dry_run:
            ctx.db.execute(
                "UPDATE like_edges SET is_stale = 1 "
                "WHERE (last_confirmed_at = '' OR last_confirmed_at < ?) AND is_stale = 0",
                (cutoff,),
            )
        result["edges_marked"] = plan.unconfirmed_edges

    # ④ 已完成任务
    if th["task_days"] > 0 and plan.task_rows:
        cutoff = _cutoff(th["task_days"])
        if not dry_run:
            ctx.db.execute(
                "DELETE FROM tasks WHERE state = 'done' "
                "AND COALESCE(finished_at, updated_at) < ?",
                (cutoff,),
            )
        result["tasks_deleted"] = plan.task_rows

    return result


def archive_stats(ctx: AppContext) -> dict[str, Any]:
    """归档现状 —— 页面上要能看到"还能撑多久"。"""
    total = ctx.db.scalar("SELECT COUNT(*) FROM raw_blobs", default=0) or 0
    pruned = ctx.db.scalar(
        "SELECT COUNT(*) FROM raw_blobs WHERE pruned_at IS NOT NULL AND pruned_at != ''",
        default=0,
    ) or 0
    live_bytes = ctx.db.scalar(
        "SELECT COALESCE(SUM(byte_size),0) FROM raw_blobs "
        "WHERE pruned_at IS NULL OR pruned_at = ''",
        default=0,
    ) or 0
    oldest = ctx.db.scalar("SELECT MIN(collected_at) FROM raw_blobs", default="") or ""

    raw_dir = ctx.paths.raw_dir
    disk_bytes = 0
    disk_files = 0
    days: list[dict[str, Any]] = []
    if raw_dir.is_dir():
        for d in sorted(raw_dir.iterdir()):
            if not d.is_dir():
                continue
            fs = [f for f in d.iterdir() if f.is_file()]
            size = sum(f.stat().st_size for f in fs)
            disk_bytes += size
            disk_files += len(fs)
            days.append({"date": d.name, "files": len(fs), "mb": round(size / 1048576, 2)})

    return {
        "rows": total,
        "pruned_rows": pruned,
        "live_bytes": live_bytes,
        "live_mb": round(live_bytes / 1048576, 2),
        "disk_bytes": disk_bytes,
        "disk_mb": round(disk_bytes / 1048576, 2),
        "disk_files": disk_files,
        "oldest": oldest,
        "days": days,
        "retention_days": ctx.config.storage.raw_retention_days,
    }
