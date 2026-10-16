"""对标账号：登记、移出与更新检查状态。作品沿用 works 表（author_sec_uid 归属）。"""
from __future__ import annotations

import re
from typing import Any

from ..util import iso

_LINK_RE = re.compile(r"douyin\.com/user/([A-Za-z0-9_\-]+)", re.I)
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{20,}$")


def parse_sec_uid(text: str) -> str | None:
    """从主页链接或原始 sec_uid 里取出标识；识别不了返回 None。"""
    value = (text or "").strip()
    if not value:
        return None
    match = _LINK_RE.search(value)
    if match:
        return match.group(1)
    if _ID_RE.match(value):
        return value
    return None


class Benchmarks:
    def __init__(self, db):
        self.db = db

    def add(self, sec_uid: str, nickname: str = "", note: str = "") -> bool:
        """登记一个对标账号；返回是否新建（重复添加只补空字段）。"""
        created = self.db.query_one(
            "SELECT sec_uid FROM benchmark_accounts WHERE sec_uid=?", (sec_uid,)) is None
        self.db.execute(
            "INSERT INTO benchmark_accounts(sec_uid,nickname,note,added_at) VALUES(?,?,?,?) "
            "ON CONFLICT(sec_uid) DO UPDATE SET "
            "nickname=COALESCE(NULLIF(excluded.nickname,''),nickname), "
            "note=COALESCE(NULLIF(excluded.note,''),note)",
            (sec_uid, nickname, note, iso()))
        return created

    def remove(self, sec_uid: str) -> None:
        self.db.execute("DELETE FROM benchmark_accounts WHERE sec_uid=?", (sec_uid,))

    def get(self, sec_uid: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM benchmark_accounts WHERE sec_uid=?", (sec_uid,))
        return dict(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        """名单 + 展示名（备注 > 已采集昵称）+ 作品数与最近作品时间。"""
        return self.db.rows_as_dicts(
            "SELECT b.*, COALESCE(NULLIF(b.nickname,''), u.nickname, '') AS display_name,"
            " (SELECT COUNT(*) FROM works w WHERE w.author_sec_uid=b.sec_uid) AS works_count,"
            " (SELECT MAX(w.create_time) FROM works w WHERE w.author_sec_uid=b.sec_uid) AS latest_work_at"
            " FROM benchmark_accounts b LEFT JOIN users u ON u.sec_uid=b.sec_uid"
            " ORDER BY b.added_at")

    def works(self, sec_uid: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.db.rows_as_dicts(
            "SELECT aweme_id, description, create_time, digg_count, comment_count, play_count"
            " FROM works WHERE author_sec_uid=?"
            " ORDER BY create_time DESC NULLS LAST, last_seen_at DESC LIMIT ?",
            (sec_uid, limit))

    def mark_checked(self, sec_uid: str, new_count: int, error: str = "") -> None:
        self.db.execute(
            "UPDATE benchmark_accounts SET last_checked_at=?, last_new_count=?, last_error=? WHERE sec_uid=?",
            (iso(), max(0, int(new_count)), (error or "")[:300], sec_uid))
