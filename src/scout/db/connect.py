"""SQLite 连接与会话封装。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..util import dumps


def connect(db_path: str | Path, *, read_only: bool = False, timeout: float = 10.0) -> sqlite3.Connection:
    path = Path(db_path)
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    target = f"file:{path.as_posix()}?mode=ro" if read_only else str(path)
    conn = sqlite3.connect(target, timeout=timeout, isolation_level=None, uri=read_only, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


class Database:
    """薄封装：查询、执行、事务、批量 upsert。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @classmethod
    def open(cls, db_path: str | Path, *, read_only: bool = False) -> "Database":
        return cls(connect(db_path, read_only=read_only))

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 查询 ────────────────────────────────────────────────

    def query(self, sql: str, params: Sequence[Any] | dict = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    def query_one(self, sql: str, params: Sequence[Any] | dict = ()) -> sqlite3.Row | None:
        cur = self.conn.execute(sql, params)
        return cur.fetchone()

    def scalar(self, sql: str, params: Sequence[Any] | dict = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None or len(row) == 0:
            return default
        value = row[0]
        return default if value is None else value

    def rows_as_dicts(self, sql: str, params: Sequence[Any] | dict = ()) -> list[dict]:
        return [dict(r) for r in self.query(sql, params)]

    # ── 写入 ────────────────────────────────────────────────

    def execute(self, sql: str, params: Sequence[Any] | dict = ()) -> int:
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def execute_many(self, sql: str, seq: Iterable[Sequence[Any]]) -> int:
        cur = self.conn.executemany(sql, seq)
        return cur.rowcount

    def upsert(
        self,
        table: str,
        key_cols: Sequence[str],
        values: dict,
        *,
        update_only: Sequence[str] | None = None,
    ) -> None:
        """按 key_cols 做 INSERT ... ON CONFLICT DO UPDATE。

        update_only 未指定时，更新除主键外的所有列。
        """
        cols = list(values)
        placeholders = ", ".join("?" for _ in cols)
        conflict = ", ".join(key_cols)
        updatable = [c for c in (update_only if update_only is not None else cols) if c not in key_cols]
        if updatable:
            assignments = ", ".join(f"{c}=excluded.{c}" for c in updatable)
            action = f"DO UPDATE SET {assignments}"
        else:
            action = "DO NOTHING"
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict}) {action}"
        )
        self.conn.execute(sql, [values[c] for c in cols])

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """显式事务。异常回滚。"""
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # ── 运维辅助 ────────────────────────────────────────────

    def log_event(self, level: str, scope: str, message: str, data: Any = None) -> None:
        from ..util import iso

        self.execute(
            "INSERT INTO event_logs (ts, level, scope, message, data_json) VALUES (?,?,?,?,?)",
            (iso(), level, scope, message, dumps(data) if data is not None else None),
        )

    def health(self) -> dict:
        try:
            self.query_one("SELECT 1")
            return {"ok": True}
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": str(exc)}
