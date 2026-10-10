"""遥测与运维状态的数据访问层。

这里只做「存取」，判断逻辑在 guard/ 里。分开是为了让策略可测、可换。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..db.connect import Database
from ..util import iso, local_day, utcnow


class Telemetry:
    def __init__(self, db: Database, *, tz: str = "Asia/Shanghai"):
        self.db = db
        self.tz = tz

    # ── 请求日志 ────────────────────────────────────────────

    def log_request(
        self,
        *,
        tier: str,
        url: str,
        status: int | None = None,
        ok: bool = False,
        byte_size: int = 0,
        duration_ms: int | None = None,
        empty_result: bool = False,
        error: str = "",
        task_id: int | None = None,
        raw_blob_id: int | None = None,
    ) -> int:
        self.db.execute(
            "INSERT INTO request_logs (ts, tier, task_id, method, url, status, ok, byte_size, "
            "duration_ms, empty_result, error, raw_blob_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                iso(), tier, task_id, "GET", url[:2000], status,
                1 if ok else 0, byte_size, duration_ms, 1 if empty_result else 0,
                error[:500], raw_blob_id,
            ),
        )
        return int(self.db.scalar("SELECT last_insert_rowid()", default=0))

    def recent_requests(
        self, limit: int = 100, *, tier: str | None = None, only_problem: bool = False
    ) -> list[dict[str, Any]]:
        where, params = [], []
        if tier:
            where.append("tier = ?")
            params.append(tier)
        if only_problem:
            where.append("(ok = 0 OR empty_result = 1)")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)
        rows = self.db.query(
            f"SELECT * FROM request_logs {clause} ORDER BY ts DESC LIMIT ?", params
        )
        return [dict(r) for r in rows]

    def request_stats(self, *, hours: int = 24) -> dict[str, Any]:
        since = iso(utcnow() - timedelta(hours=hours))
        total = int(self.db.scalar("SELECT COUNT(*) FROM request_logs WHERE ts >= ?", (since,), default=0))
        ok = int(self.db.scalar(
            "SELECT COUNT(*) FROM request_logs WHERE ts >= ? AND ok = 1", (since,), default=0
        ))
        empty = int(self.db.scalar(
            "SELECT COUNT(*) FROM request_logs WHERE ts >= ? AND empty_result = 1", (since,), default=0
        ))
        avg_ms = self.db.scalar(
            "SELECT AVG(duration_ms) FROM request_logs WHERE ts >= ? AND duration_ms IS NOT NULL",
            (since,), default=0,
        )
        return {
            "window_hours": hours,
            "total": total,
            "ok": ok,
            "empty": empty,
            "failed": total - ok,
            "ok_rate": round(ok / total, 4) if total else None,
            "empty_rate": round(empty / total, 4) if total else None,
            "avg_duration_ms": int(avg_ms or 0),
        }

    def requests_by_hour(self, *, hours: int = 24) -> list[dict[str, Any]]:
        since = iso(utcnow() - timedelta(hours=hours))
        rows = self.db.query(
            "SELECT substr(ts, 1, 13) AS hour, COUNT(*) AS n, "
            "SUM(ok) AS ok, SUM(empty_result) AS empty "
            "FROM request_logs WHERE ts >= ? GROUP BY hour ORDER BY hour",
            (since,),
        )
        return [dict(r) for r in rows]

    # ── 配额账本 ────────────────────────────────────────────

    def quota_used(self, tier: str, day: str | None = None) -> int:
        day = day or local_day(self.tz)
        return int(self.db.scalar(
            "SELECT used FROM quota_ledger WHERE day=? AND tier=?", (day, tier), default=0
        ))

    def quota_add(self, tier: str, limit: int | None, *, day: str | None = None, n: int = 1) -> int:
        day = day or local_day(self.tz)
        self.db.execute(
            "INSERT INTO quota_ledger (day, tier, used, limit_value) VALUES (?,?,?,?) "
            "ON CONFLICT(day, tier) DO UPDATE SET used = used + ?, limit_value = excluded.limit_value",
            (day, tier, n, limit, n),
        )
        return self.quota_used(tier, day)

    def quota_all(self, day: str | None = None) -> list[dict[str, Any]]:
        day = day or local_day(self.tz)
        return self.db.rows_as_dicts(
            "SELECT * FROM quota_ledger WHERE day=? ORDER BY tier", (day,)
        )

    def quota_reset(self, tier: str | None = None, day: str | None = None) -> int:
        """把配额账本清零。

        什么时候需要：口径修正（比如原来把静态资源也算进去了）、
        误操作把额度烧掉、或你确认要临时多跑一轮。
        **不是常规操作**，动它之前先想清楚为什么。
        """
        day = day or local_day(self.tz)
        if tier:
            return self.db.execute(
                "DELETE FROM quota_ledger WHERE day=? AND tier=?", (day, tier)
            )
        return self.db.execute("DELETE FROM quota_ledger WHERE day=?", (day,))

    def quota_set(self, tier: str, used: int, *, limit: int | None = None,
                  day: str | None = None) -> None:
        """把某个档位今天的用量直接设成指定值（口径修正用）。"""
        day = day or local_day(self.tz)
        self.db.execute(
            "INSERT INTO quota_ledger (day, tier, used, limit_value) VALUES (?,?,?,?) "
            "ON CONFLICT(day, tier) DO UPDATE SET used=excluded.used, "
            "limit_value=excluded.limit_value",
            (day, tier, int(used), limit),
        )

    def quota_history(self, days: int = 14) -> list[dict[str, Any]]:
        return self.db.rows_as_dicts(
            "SELECT * FROM quota_ledger WHERE day >= date('now', ?) ORDER BY day DESC, tier",
            (f"-{int(days)} days",),
        )

    # ── 熔断状态 ────────────────────────────────────────────

    def circuit_load(self, key: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM circuit_state WHERE key=?", (key,))
        if row is None:
            self.db.execute(
                "INSERT INTO circuit_state (key, state, updated_at) VALUES (?, 'closed', ?)",
                (key, iso()),
            )
            row = self.db.query_one("SELECT * FROM circuit_state WHERE key=?", (key,))
        return dict(row)

    def circuit_save(self, key: str, **fields: Any) -> None:
        fields["updated_at"] = iso()
        cols = list(fields)
        assignments = ", ".join(f"{c}=?" for c in cols)
        self.db.execute(
            f"UPDATE circuit_state SET {assignments} WHERE key=?",
            [*[fields[c] for c in cols], key],
        )

    def circuit_all(self) -> list[dict[str, Any]]:
        return self.db.rows_as_dicts("SELECT * FROM circuit_state ORDER BY key")

    # ── 事件日志 ────────────────────────────────────────────

    def events(self, limit: int = 100, *, level: str | None = None) -> list[dict[str, Any]]:
        if level:
            rows = self.db.query(
                "SELECT * FROM event_logs WHERE level=? ORDER BY ts DESC LIMIT ?", (level, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM event_logs ORDER BY ts DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def error_summary(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT error, COUNT(*) n, MAX(ts) last_at FROM request_logs "
            "WHERE ok = 0 AND error != '' GROUP BY error ORDER BY n DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
