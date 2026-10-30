"""按人删除：删掉某个互动者在本机的全部数据。

适用场景：互动者要求删除其个人信息，或使用者要清理某个账号的痕迹。

删除范围（都在当前账号的本地库里）：
    users / like_edges / comments / user_snapshots / user_work_listings /
    llm_results（活体分析）/ tasks 与 collection_*（该人的待办）/ 该人公开作品的样本

**不删除**：归档正文（`raw/`，按时间段整体清理）、导出 CSV、备份。
这两条在 docs/privacy.md 里写清楚，避免误以为"点了删除就彻底没了"。
"""

from __future__ import annotations

from typing import Any

from ..util import iso


def clean_uid(value: str) -> str:
    text = str(value or "").strip()
    if len(text) < 4 or len(text) > 200 or any(ch.isspace() for ch in text):
        raise ValueError("账号 ID 格式不对")
    return text


class ForgetPerson:
    def __init__(self, db):
        self.db = db

    # ── 统计 ────────────────────────────────────────────────

    def _work_ids(self, uid: str) -> list[str]:
        return [str(row["aweme_id"]) for row in self.db.query(
            "SELECT aweme_id FROM works WHERE author_sec_uid = ? AND is_mine = 0", (uid,))]

    def _counts(self, uid: str) -> dict[str, int]:
        work_ids = self._work_ids(uid)
        marks = ",".join("?" * len(work_ids))
        counts = {
            "users": self.db.scalar("SELECT COUNT(*) FROM users WHERE sec_uid = ?", (uid,), default=0),
            "like_edges": self.db.scalar("SELECT COUNT(*) FROM like_edges WHERE sec_uid = ?", (uid,), default=0),
            "comments": self.db.scalar("SELECT COUNT(*) FROM comments WHERE sec_uid = ?", (uid,), default=0),
            "snapshots": self.db.scalar("SELECT COUNT(*) FROM user_snapshots WHERE sec_uid = ?", (uid,), default=0),
            "listings": self.db.scalar("SELECT COUNT(*) FROM user_work_listings WHERE sec_uid = ?", (uid,), default=0),
            "analyses": self.db.scalar(
                "SELECT COUNT(*) FROM llm_results WHERE subject_kind = 'user' AND subject_id = ?",
                (uid,), default=0),
            "tasks": self.db.scalar(
                "SELECT COUNT(*) FROM tasks WHERE target = ? AND kind IN ('fetch_profile','fetch_user_works')",
                (uid,), default=0),
            "coverage": self.db.scalar(
                "SELECT COUNT(*) FROM collection_coverage WHERE target = ?"
                " AND kind IN ('fetch_profile','fetch_user_works')", (uid,), default=0),
            "works": len(work_ids),
            "work_edges": self.db.scalar(
                f"SELECT COUNT(*) FROM like_edges WHERE aweme_id IN ({marks})", tuple(work_ids), default=0)
            if work_ids else 0,
            "work_comments": self.db.scalar(
                f"SELECT COUNT(*) FROM comments WHERE aweme_id IN ({marks})", tuple(work_ids), default=0)
            if work_ids else 0,
        }
        counts["total"] = sum(value for key, value in counts.items() if key != "users")
        return counts

    def preview(self, sec_uid: str) -> dict[str, Any]:
        uid = clean_uid(sec_uid)
        exists = bool(self.db.scalar("SELECT COUNT(*) FROM users WHERE sec_uid = ?", (uid,), default=0))
        return {"sec_uid": uid, "exists": exists, **self._counts(uid)}

    # ── 删除 ────────────────────────────────────────────────

    def delete(self, sec_uid: str) -> dict[str, Any]:
        uid = clean_uid(sec_uid)
        counts = self._counts(uid)
        if not counts["users"] and not counts["total"]:
            raise LookupError("没有这个人的数据")
        with self.db.transaction() as conn:
            work_ids = self._work_ids(uid)
            if work_ids:
                marks = ",".join("?" * len(work_ids))
                params = tuple(work_ids)
                conn.execute(f"DELETE FROM like_edges WHERE aweme_id IN ({marks})", params)
                conn.execute(f"DELETE FROM comments WHERE aweme_id IN ({marks})", params)
                conn.execute(f"DELETE FROM user_work_listings WHERE aweme_id IN ({marks})", params)
                conn.execute(f"DELETE FROM enterprise_metrics WHERE aweme_id IN ({marks})", params)
                conn.execute(f"DELETE FROM works WHERE aweme_id IN ({marks})", params)
            conn.execute("DELETE FROM like_edges WHERE sec_uid = ?", (uid,))
            conn.execute("DELETE FROM comments WHERE sec_uid = ?", (uid,))
            conn.execute("DELETE FROM user_snapshots WHERE sec_uid = ?", (uid,))
            conn.execute("DELETE FROM user_work_listings WHERE sec_uid = ?", (uid,))
            conn.execute("DELETE FROM llm_results WHERE subject_kind = 'user' AND subject_id = ?", (uid,))
            conn.execute(
                "DELETE FROM tasks WHERE target = ? AND kind IN ('fetch_profile','fetch_user_works')", (uid,))
            conn.execute(
                "DELETE FROM collection_items WHERE target = ?"
                " AND kind IN ('fetch_profile','fetch_user_works')", (uid,))
            conn.execute(
                "DELETE FROM collection_coverage WHERE target = ?"
                " AND kind IN ('fetch_profile','fetch_user_works')", (uid,))
            conn.execute("DELETE FROM users WHERE sec_uid = ?", (uid,))
        self.db.log_event("warning", "privacy", "按人删除：互动者数据已清除",
                          {"sec_uid": uid[:12] + "…", "counts": counts, "at": iso()})
        return {"sec_uid": uid, "deleted": counts}
