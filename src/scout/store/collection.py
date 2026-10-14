"""Collection coverage and reversible audience-quality views."""
from __future__ import annotations

from datetime import timedelta
from ..util import iso, utcnow


class Coverage:
    def __init__(self, db):
        self.db = db

    def get(self, kind, target):
        row = self.db.query_one("SELECT * FROM collection_coverage WHERE kind=? AND target=?", (kind, target))
        return dict(row) if row else None

    def save(self, kind, target, *, state, item_count=0, item_limit=0, next_cursor=0, pages=0, error="", hint=""):
        self.db.upsert("collection_coverage", ("kind", "target"), {
            "kind": kind, "target": target, "state": state, "item_count": item_count,
            "item_limit": item_limit, "next_cursor": next_cursor, "pages": pages,
            "error": error, "updated_at": iso(), "hint": hint,
        })

    def fresh(self, kind, target, *, required=0, ttl_hours=24, hint=None):
        row = self.get(kind, target)
        if not row or row["updated_at"] < iso(utcnow() - timedelta(hours=ttl_hours)):
            return False
        if hint is not None and row["hint"] != hint:
            return False
        return row["state"] in ("full", "empty") or (
            row["state"] == "sampled" and required > 0 and row["item_count"] >= required)

    def items(self, kind, target):
        return {r["item_id"] for r in self.db.query("SELECT item_id FROM collection_items WHERE kind=? AND target=?", (kind, target))}

    def reset_items(self, kind, target):
        self.db.execute("DELETE FROM collection_items WHERE kind=? AND target=?", (kind, target))

    def add_items(self, kind, target, identifiers):
        self.db.execute_many("INSERT OR IGNORE INTO collection_items(kind,target,item_id) VALUES(?,?,?)",
                             ((kind, target, item) for item in identifiers))

    def mark_absent_likers(self, target):
        return self.db.execute("""UPDATE like_edges SET is_stale=1 WHERE aweme_id=? AND sec_uid NOT IN
            (SELECT item_id FROM collection_items WHERE kind='fetch_likers' AND target=?)""", (target,target))


class Quality:
    def __init__(self, db):
        self.db = db

    def audience(self, *, limit=None, repeated_only=False):
        sql = "SELECT * FROM v_audience_quality WHERE interaction_works>0"
        if repeated_only:
            sql += " AND interaction_works>=2"
        sql += " ORDER BY interaction_works DESC, sec_uid"
        return self.db.rows_as_dicts(sql + (" LIMIT ?" if limit is not None else ""), (limit,) if limit is not None else ())

    def refresh_staleness(self, days):
        if days > 0:
            self.db.execute("UPDATE like_edges SET is_stale=1 WHERE COALESCE(NULLIF(last_confirmed_at,''),discovered_at) < ?",
                            (iso(utcnow()-timedelta(days=days)),))

    def report(self):
        counts = self.db.query_one("""SELECT COUNT(*) AS active_users,
            COALESCE(SUM(interaction_works>=2),0) AS repeated_users,
            COALESCE(SUM(data_status='资料待补'),0) AS incomplete_profiles,
            COALESCE(SUM(sample_count=0),0) AS without_samples
            FROM v_audience_quality WHERE interaction_works>0""")
        out = dict(counts)
        out["raw_edges"] = self.db.scalar("SELECT COUNT(*) FROM like_edges", default=0)
        out["valid_edges"] = self.db.scalar("SELECT COUNT(*) FROM v_valid_interactions", default=0)
        out["stale_edges"] = self.db.scalar("SELECT COUNT(*) FROM like_edges WHERE is_stale=1", default=0)
        out["invalid_edges"] = self.db.scalar("""SELECT COUNT(*) FROM like_edges le
            LEFT JOIN users u ON u.sec_uid=le.sec_uid LEFT JOIN works w ON w.aweme_id=le.aweme_id
            WHERE le.sec_uid='' OR le.aweme_id='' OR u.sec_uid IS NULL OR w.aweme_id IS NULL
               OR w.is_mine<>1 OR le.notice_kind<>'digg'""", default=0)
        out["duplicate_edges"] = self.db.scalar("""SELECT COALESCE(SUM(n-1),0) FROM (
            SELECT COUNT(*) AS n FROM like_edges GROUP BY sec_uid,aweme_id HAVING COUNT(*)>1)""", default=0)
        out["anomalous_works"] = self.db.scalar("SELECT COUNT(*) FROM works WHERE stats_anomaly<>''", default=0)
        return out


class CollectionQueue:
    """Claim exactly the planned target without rearming unrelated tasks."""
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.db

    def claim(self, kind, target, tier, force=False):
        now = iso()
        with self.db.transaction():
            self.ctx.tasks.enqueue(kind, target, tier, priority=20)
            row = self.db.query_one("SELECT * FROM tasks WHERE kind=? AND target=? AND tier=?", (kind,target,tier))
            if row["state"] == "running":
                return None
            if not force and row["state"] != "done" and row["available_at"] > now:
                return None
            if row["state"] == "failed" and not force and row["attempts"] >= row["max_attempts"]:
                return None
            attempts = 0 if row["state"] == "done" or force else row["attempts"]
            self.db.execute("UPDATE tasks SET state='running',attempts=?,claimed_at=?,finished_at=NULL,updated_at=? WHERE id=?",
                            (attempts+1,now,now,row["id"]))
            return dict(self.db.query_one("SELECT * FROM tasks WHERE id=?", (row["id"],)))

    def release(self, task):
        self.db.execute("UPDATE tasks SET state='pending',claimed_at=NULL,attempts=MAX(0,attempts-1) WHERE id=?", (task["id"],))


def clean_metrics(record):
    """Normalize a copy for presentation/analysis; original records stay available."""
    out = dict(record)
    for name in ("digg_count", "comment_count", "share_count", "collect_count", "play_count",
                 "follower_count", "following_count", "total_favorited", "aweme_count"):
        value = out.get(name)
        if isinstance(value, (int, float)) and value < 0:
            out[name] = None
    for name in ("nickname", "description", "signature"):
        if isinstance(out.get(name), str):
            out[name] = out[name].strip()
    return out
