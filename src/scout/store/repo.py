"""实体仓储：用户、作品、点赞边、快照、任务、游标。

约定：
- 所有写入幂等（upsert），重复采集不产生脏数据、不报错。
- 只在这里写 SQL，业务层不碰 SQL 字符串。
- 时间统一用 util.iso() 的 UTC 格式。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from ..config import BackoffConfig
from ..db.connect import Database
from .quality import check_stats
from ..util import dumps, iso, local_day, loads, parse_iso, utcnow


def _now() -> str:
    return iso()


# ── 用户 ─────────────────────────────────────────────────────


class Users:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, record: dict[str, Any], *, raw_blob_id: int | None = None) -> None:
        """写入/更新一个用户。record 里没有的字段保持原值。"""
        sec_uid = (record.get("sec_uid") or "").strip()
        if not sec_uid:
            return
        now = _now()
        fields: dict[str, Any] = {
            "sec_uid": sec_uid,
            "last_seen_at": now,
            "first_seen_at": record.get("first_seen_at") or now,
        }
        for col in (
            "uid", "douyin_id", "nickname", "signature", "avatar_url", "gender",
            "region", "ip_location", "follower_count", "following_count",
            "total_favorited", "aweme_count", "verification", "is_verified",
            "discovered_from",
        ):
            if record.get(col) is not None:
                fields[col] = record[col]
        if raw_blob_id is not None:
            fields["raw_blob_id"] = raw_blob_id
        if record.get("profile_state"):
            fields["profile_state"] = record["profile_state"]
            fields["profile_attempts"] = 0
            fields["profile_fetched_at"] = now
            if record.get("profile_tier"):
                fields["profile_tier"] = record["profile_tier"]

        cols = list(fields)
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "sec_uid")
        self.db.execute(
            f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(sec_uid) DO UPDATE SET {updates}",
            [fields[c] for c in cols],
        )

    def ensure(self, sec_uid: str, *, discovered_from: str = "") -> None:
        """只保证这条用户存在，方便后续任务排队。"""
        if not sec_uid:
            return
        now = _now()
        self.db.execute(
            "INSERT INTO users (sec_uid, first_seen_at, last_seen_at, discovered_from) "
            "VALUES (?,?,?,?) ON CONFLICT(sec_uid) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            (sec_uid, now, now, discovered_from),
        )

    def mark_state(self, sec_uid: str, state: str, *, tier: str = "", error: str = "") -> None:
        self.db.execute(
            "UPDATE users SET profile_state=?, profile_attempts=profile_attempts+1, "
            "profile_tier=?, last_seen_at=? WHERE sec_uid=?",
            (state, tier, _now(), sec_uid),
        )
        if error:
            self.db.log_event("warn", f"user:{sec_uid}", f"状态 {state}：{error}")

    def get(self, sec_uid: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM users WHERE sec_uid = ?", (sec_uid,))
        return dict(row) if row else None

    def needs_profile(self, limit: int = 100, *, max_attempts: int = 5) -> list[str]:
        rows = self.db.query(
            "SELECT u.sec_uid FROM users u "
            "LEFT JOIN (SELECT sec_uid, COUNT(*) c FROM like_edges GROUP BY sec_uid) le "
            "  ON le.sec_uid = u.sec_uid "
            "WHERE u.profile_state IN ('pending','error','blocked') AND u.profile_attempts < ? "
            "ORDER BY COALESCE(le.c,0) DESC, u.last_seen_at ASC LIMIT ?",
            (max_attempts, limit),
        )
        return [r["sec_uid"] for r in rows]

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        state: str | None = None,
        order: str = "like_count",
    ) -> list[dict[str, Any]]:
        order_sql = {
            "like_count": "like_count DESC, last_seen_at DESC",
            "fans": "follower_count DESC NULLS LAST, last_seen_at DESC",
            "recent": "last_seen_at DESC",
            "nickname": "nickname ASC",
        }.get(order, "like_count DESC")
        where = "WHERE profile_state = ?" if state else ""
        params: list[Any] = [state] if state else []
        params.extend([limit, offset])
        rows = self.db.query(
            f"""
            SELECT u.*, COALESCE(le.c,0) AS like_count
            FROM users u
            LEFT JOIN (SELECT sec_uid, COUNT(*) c FROM like_edges GROUP BY sec_uid) le
              ON le.sec_uid = u.sec_uid
            {where}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return [dict(r) for r in rows]

    def need_works(self, limit: int = 200) -> list[str]:
        """哪些点赞人还需要采作品列表（AI 画像的原料）。

        判据：是他点了赞的人，且还没有作品列表记录。
        粉丝多的优先 —— 他们更可能有值得分析的内容。
        """
        rows = self.db.query(
            """
            SELECT u.sec_uid
            FROM users u
            WHERE u.sec_uid IN (SELECT sec_uid FROM like_edges)
              AND NOT EXISTS (
                    SELECT 1 FROM user_work_listings l WHERE l.sec_uid = u.sec_uid
              )
            ORDER BY COALESCE(u.follower_count, -1) DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [r["sec_uid"] for r in rows]

    def stats(self) -> dict[str, Any]:
        return {
            "total": self.db.scalar("SELECT COUNT(*) FROM users", default=0),
            "pending": self.db.scalar(
                "SELECT COUNT(*) FROM users WHERE profile_state='pending'", default=0
            ),
            "ok": self.db.scalar("SELECT COUNT(*) FROM users WHERE profile_state='ok'", default=0),
            "wall": self.db.scalar(
                "SELECT COUNT(*) FROM users WHERE profile_state IN ('login_wall','blocked')", default=0
            ),
            "error": self.db.scalar(
                "SELECT COUNT(*) FROM users WHERE profile_state='error'", default=0
            ),
            "with_works": self.db.scalar(
                "SELECT COUNT(DISTINCT sec_uid) FROM user_work_listings", default=0
            ),
        }


class UserSnapshots:
    """用户指标快照。注意：只存当前值会丢掉趋势，所以必须按天留痕。"""

    def __init__(self, db: Database):
        self.db = db

    def record(self, sec_uid: str, metrics: dict[str, Any], *, day: str | None = None) -> None:
        day = day or local_day()
        self.db.upsert(
            "user_snapshots",
            ("sec_uid", "day"),
            {
                "sec_uid": sec_uid,
                "day": day,
                "follower_count": metrics.get("follower_count"),
                "following_count": metrics.get("following_count"),
                "total_favorited": metrics.get("total_favorited"),
                "aweme_count": metrics.get("aweme_count"),
                "captured_at": _now(),
            },
        )

    def history(self, sec_uid: str, limit: int = 60) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM user_snapshots WHERE sec_uid = ? ORDER BY day DESC LIMIT ?",
            (sec_uid, limit),
        )
        return [dict(r) for r in rows]


# ── 作品 ─────────────────────────────────────────────────────


class Works:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, record: dict[str, Any], *, raw_blob_id: int | None = None) -> None:
        aweme_id = str(record.get("aweme_id") or "").strip()
        if not aweme_id:
            return
        now = _now()
        fields: dict[str, Any] = {
            "aweme_id": aweme_id,
            "first_seen_at": record.get("first_seen_at") or now,
            "last_seen_at": now,
        }
        for col in (
            "author_sec_uid", "description", "create_time", "duration_ms", "digg_count",
            "comment_count", "share_count", "collect_count", "play_count", "music_title",
            "cover_url", "share_url", "is_top", "is_mine",
        ):
            if record.get(col) is not None:
                fields[col] = record[col]
        if record.get("hashtags") is not None:
            fields["hashtags_json"] = dumps(record["hashtags"])
        if raw_blob_id is not None:
            fields["raw_blob_id"] = raw_blob_id
        if any(record.get(k) is not None for k in ("digg_count", "comment_count", "share_count")):
            fields["stats_fetched_at"] = now
            # 合理性校验：反常数字**标注出来**，不修改（见 store/quality.py）
            fields["stats_anomaly"] = check_stats(record)

        cols = list(fields)
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "aweme_id")
        self.db.execute(
            f"INSERT INTO works ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(aweme_id) DO UPDATE SET {updates}",
            [fields[c] for c in cols],
        )

    def mark_mine(self, author_sec_uid: str) -> int:
        return self.db.execute(
            "UPDATE works SET is_mine = 1 WHERE author_sec_uid = ?", (author_sec_uid,)
        )

    def get(self, aweme_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM works WHERE aweme_id = ?", (aweme_id,))
        return dict(row) if row else None

    def list(self, *, limit: int = 50, offset: int = 0, mine_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE is_mine = 1" if mine_only else ""
        rows = self.db.query(
            f"SELECT * FROM works {where} ORDER BY create_time DESC NULLS LAST, last_seen_at DESC "
            f"LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows]

    def link_listings(self, sec_uid: str, aweme_ids: Sequence[str], *, raw_blob_id: int | None = None) -> None:
        now = _now()
        rows = [
            (sec_uid, str(aid), idx, now, raw_blob_id)
            for idx, aid in enumerate(aweme_ids)
            if aid
        ]
        if not rows:
            return
        self.db.execute_many(
            "INSERT INTO user_work_listings (sec_uid, aweme_id, position, listed_at, raw_blob_id) "
            "VALUES (?,?,?,?,?) ON CONFLICT(sec_uid, aweme_id) DO UPDATE SET "
            "position=excluded.position, listed_at=excluded.listed_at",
            rows,
        )

    def need_stats_refresh(self, ttl_days: int, limit: int = 200) -> list[tuple[str, str]]:
        """哪些作品的统计已经过期，需要重新采一遍。

        返回 [(sec_uid, aweme_id), ...] —— 知道作者才能走作品列表接口刷新。

        **为什么需要这个**：作品数据是会变的（点赞、评论一直涨）。
        之前采一次就永远不更新，页面上显示的是一个冻结的数字，
        而且不告诉用户它是什么时候的 —— 那等于在误导。
        """
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(0, ttl_days))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        rows = self.db.query(
            """
            SELECT l.sec_uid, w.aweme_id
            FROM user_work_listings l
            JOIN works w ON w.aweme_id = l.aweme_id
            WHERE COALESCE(w.stats_fetched_at, '') < ?
            ORDER BY COALESCE(w.digg_count, 0) DESC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        return [(r["sec_uid"], r["aweme_id"]) for r in rows]

    def stats_age_stats(self) -> dict[str, Any]:
        """统计数据的时效分布 —— 页面上用来告诉你"这些数字有多旧"。"""
        return {
            "with_time": self.db.scalar(
                "SELECT COUNT(*) FROM works WHERE stats_fetched_at IS NOT NULL AND stats_fetched_at != ''",
                default=0,
            ),
            "anomalous": self.db.scalar(
                "SELECT COUNT(*) FROM works WHERE stats_anomaly != ''", default=0
            ),
            "oldest": self.db.scalar(
                "SELECT MIN(stats_fetched_at) FROM works WHERE stats_fetched_at IS NOT NULL",
                default="",
            ),
        }

    def mark_mine_by_author(self, sec_uid: str) -> int:
        """按作者本人 sec_uid 标记我的作品。**这是可靠的判据。**"""
        if not sec_uid:
            return 0
        return self.db.execute(
            "UPDATE works SET is_mine = 1 WHERE author_sec_uid = ? AND is_mine = 0",
            (sec_uid,),
        )

    def mark_mine(self) -> int:
        """启发式兜底：从通知流发现的作品，作者就是我自己。

        只在还不知道自己 sec_uid 时用（见 SelfCollector）。
        判据弱：点赞边被清理过之后就失效，所以主力还是 mark_mine_by_author。
        """
        return self.db.execute(
            """
            UPDATE works SET is_mine = 1
            WHERE is_mine = 0
              AND aweme_id IN (
                    SELECT DISTINCT aweme_id FROM like_edges
                    WHERE aweme_id != '' AND notice_id NOT LIKE 'api:%'
              )
            """
        )

    def mine(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM works WHERE is_mine = 1 ORDER BY create_time DESC NULLS LAST, digg_count DESC"
        )
        return [dict(r) for r in rows]

    def need_likers(self, limit: int = 200) -> list[str]:
        """哪些作品还需要去拉完整点赞人名单。

        **只针对我自己的作品**（is_mine=1），绝不扩散到点赞人的作品 ——
        否则就变成"点赞人的点赞人"，无限套娃把请求量拉爆。

        判据：是我的作品、有赞、且还没通过接口拿过完整名单。
        """
        rows = self.db.query(
            """
            SELECT w.aweme_id
            FROM works w
            WHERE w.is_mine = 1
              AND COALESCE(w.digg_count, 0) > 0
              AND NOT EXISTS (
                    SELECT 1 FROM like_edges le
                    WHERE le.aweme_id = w.aweme_id AND le.notice_id LIKE 'api:%'
              )
            ORDER BY w.digg_count DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [r["aweme_id"] for r in rows]

    def stats(self) -> dict[str, Any]:
        return {
            "total": self.db.scalar("SELECT COUNT(*) FROM works", default=0),
            "mine": self.db.scalar("SELECT COUNT(*) FROM works WHERE is_mine=1", default=0),
            "today": self.db.scalar(
                "SELECT COUNT(*) FROM works WHERE last_seen_at >= ?",
                (iso()[:10] + "T00:00:00Z",),
                default=0,
            ),
        }


# ── 点赞边 ───────────────────────────────────────────────────


class LikeEdges:
    def __init__(self, db: Database):
        self.db = db

    def add_many(self, edges: Iterable[dict[str, Any]], *, tier: str = "a", raw_blob_id: int | None = None) -> int:
        now = _now()
        rows = []
        for e in edges:
            sec_uid = str(e.get("sec_uid") or "").strip()
            if not sec_uid:
                continue
            rows.append(
                (
                    sec_uid,
                    str(e.get("aweme_id") or ""),
                    str(e.get("notice_id") or ""),
                    str(e.get("notice_kind") or "digg"),
                    e.get("discovered_at") or now,
                    tier,
                    raw_blob_id,
                    e.get("merge_count"),
                    1 if e.get("has_more_likers") else 0,
                    e.get("notice_type"),
                    str(e.get("source_url") or ""),
                )
            )
        if not rows:
            return 0
        before = self.db.scalar("SELECT COUNT(*) FROM like_edges", default=0)
        self.db.execute_many(
            "INSERT INTO like_edges (sec_uid, aweme_id, notice_id, notice_kind, discovered_at, "
            "tier, raw_blob_id, merge_count, has_more_likers, notice_type, source_url) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(sec_uid, aweme_id, notice_id) DO UPDATE SET "
            "merge_count=COALESCE(excluded.merge_count, like_edges.merge_count), "
            "has_more_likers=MAX(excluded.has_more_likers, like_edges.has_more_likers)",
            rows,
        )
        after = self.db.scalar("SELECT COUNT(*) FROM like_edges", default=0)
        return int(after) - int(before)

    def incomplete(self, limit: int = 50) -> list[dict[str, Any]]:
        """还缺人的作品：聚合数大于已拿到的人数。这些才值得去点开「赞过的人」。"""
        return self.db.rows_as_dicts(
            "SELECT * FROM v_like_edges_incomplete ORDER BY expected DESC LIMIT ?", (limit,)
        )

    def top_likers(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT le.sec_uid, u.nickname, u.douyin_id, u.follower_count,
                   COUNT(*) AS like_count, MAX(le.discovered_at) AS last_like_at
            FROM like_edges le LEFT JOIN users u ON u.sec_uid = le.sec_uid
            GROUP BY le.sec_uid
            ORDER BY like_count DESC, last_like_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        return {
            "total": self.db.scalar("SELECT COUNT(*) FROM like_edges", default=0),
            "distinct_users": self.db.scalar(
                "SELECT COUNT(DISTINCT sec_uid) FROM like_edges", default=0
            ),
            "today": self.db.scalar(
                "SELECT COUNT(*) FROM like_edges WHERE discovered_at >= ?",
                (iso()[:10] + "T00:00:00Z",),
                default=0,
            ),
        }


# ── 任务队列 ─────────────────────────────────────────────────


class Tasks:
    """SQLite 支撑的任务队列。

    关键性质：
    - claim 是原子的（先选 id，再用 state='pending' 做条件更新）。
    - 进程崩溃后 running 任务由 reclaim_stuck 捞回，不会永久卡死。
    - 失败按指数退避重排，到达 max_attempts 才置 failed。
    """

    def __init__(self, db: Database, backoff: BackoffConfig | None = None):
        self.db = db
        self.backoff = backoff or BackoffConfig()

    def enqueue(
        self,
        kind: str,
        target: str,
        tier: str,
        *,
        priority: int = 100,
        payload: dict | None = None,
        max_attempts: int = 5,
    ) -> bool:
        """插入任务；已存在则不打扰（返回 False）。"""
        if not target:
            return False
        now = _now()
        cur = self.db.execute(
            "INSERT INTO tasks (kind, target, tier, priority, state, attempts, max_attempts, "
            "available_at, payload_json, created_at, updated_at) "
            "VALUES (?,?,?,?,'pending',0,?,?,?,?,?) "
            "ON CONFLICT(kind, target, tier) DO NOTHING",
            (kind, target, tier, priority, max_attempts, now, dumps(payload or {}), now, now),
        )
        return cur > 0

    def enqueue_many(self, items: Iterable[tuple[str, str, str]], *, priority: int = 100) -> int:
        return sum(1 for kind, target, tier in items if self.enqueue(kind, target, tier, priority=priority))

    def claim(self, tier: str, limit: int = 1, *, kinds: Sequence[str] | None = None) -> list[dict[str, Any]]:
        now = _now()
        kind_clause, params = "", [tier, now]
        if kinds:
            marks = ", ".join("?" for _ in kinds)
            kind_clause = f"AND kind IN ({marks})"
            params.extend(kinds)
        params.append(limit)
        rows = self.db.query(
            f"SELECT id FROM tasks WHERE state='pending' AND tier=? AND available_at<=? "
            f"{kind_clause} ORDER BY priority ASC, id ASC LIMIT ?",
            params,
        )
        ids = [int(r["id"]) for r in rows]
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        self.db.execute(
            f"UPDATE tasks SET state='running', claimed_at=?, attempts=attempts+1, updated_at=? "
            f"WHERE id IN ({marks}) AND state='pending'",
            [now, now, *ids],
        )
        claimed = self.db.query(
            f"SELECT * FROM tasks WHERE id IN ({marks}) AND state='running' AND claimed_at=?",
            [*ids, now],
        )
        return [dict(r) for r in claimed]

    def rearm(self, kind: str, target: str, tier: str, *, min_interval_minutes: int = 0,
              priority: int = 100) -> bool:
        """把已经跑完的任务重新排上（周期任务用）。

        为什么需要：enqueue 因为有唯一约束，对 done 的任务返回 False。
        结果就是互动消息采集只能跑一次，之后 `scout run` 什么都不做 ——
        而它本该是每天都要跑的东西。

        min_interval_minutes > 0 时，距上次完成不足这个间隔就跳过，
        防止连续手滑触发多次。
        """
        row = self.db.query_one(
            "SELECT id, state, finished_at FROM tasks WHERE kind=? AND target=? AND tier=?",
            (kind, target, tier),
        )
        if row is None:
            return self.enqueue(kind, target, tier, priority=priority)

        if row["state"] in ("pending", "running"):
            return False

        finished = row["finished_at"]
        if min_interval_minutes > 0 and finished:
            try:
                age_min = (utcnow() - parse_iso(finished)).total_seconds() / 60
            except Exception:
                age_min = 0
            if age_min < min_interval_minutes:
                return False

        now = _now()
        self.db.execute(
            "UPDATE tasks SET state='pending', attempts=0, claimed_at=NULL, finished_at=NULL, "
            "available_at=?, last_error='', priority=?, updated_at=? WHERE id=?",
            (now, priority, now, row["id"]),
        )
        return True

    def rearm_kinds(self, kinds: Sequence[str], *, min_interval_minutes: int = 0) -> int:
        """把指定 kind 的已结束任务全部重新排上。`scout run --kind X` 用它。"""
        if not kinds:
            return 0
        marks = ", ".join("?" for _ in kinds)
        return self.db.execute(
            f"UPDATE tasks SET state='pending', attempts=0, claimed_at=NULL, finished_at=NULL, "
            f"available_at=?, last_error='', updated_at=? "
            f"WHERE kind IN ({marks}) AND state IN ('done','failed','blocked')",
            (_now(), _now(), *kinds),
        )

    def complete(self, task_id: int) -> None:
        self.db.execute(
            "UPDATE tasks SET state='done', finished_at=?, updated_at=?, last_error='' WHERE id=?",
            (_now(), _now(), task_id),
        )

    def fail(self, task_id: int, error: str, *, retry: bool = True) -> str:
        row = self.db.query_one("SELECT attempts, max_attempts, kind FROM tasks WHERE id=?", (task_id,))
        if row is None:
            return "missing"
        attempts, max_attempts = int(row["attempts"]), int(row["max_attempts"])
        if not retry or attempts >= max_attempts:
            self.db.execute(
                "UPDATE tasks SET state='failed', finished_at=?, updated_at=?, last_error=? WHERE id=?",
                (_now(), _now(), error[:500], task_id),
            )
            return "failed"
        delay = min(self.backoff.base_s * (self.backoff.factor ** max(0, attempts - 1)), self.backoff.max_s)
        from datetime import timedelta

        next_at = iso(utcnow() + timedelta(seconds=delay))
        self.db.execute(
            "UPDATE tasks SET state='pending', available_at=?, updated_at=?, last_error=? WHERE id=?",
            (next_at, _now(), error[:500], task_id),
        )
        return "retry"

    def reclaim_stuck(self, older_than_minutes: int = 30) -> int:
        """进程崩溃后把卡在 running 的任务捞回。启动时必调。"""
        from datetime import timedelta

        cutoff = iso(utcnow() - timedelta(minutes=older_than_minutes))
        n = self.db.execute(
            "UPDATE tasks SET state='pending', claimed_at=NULL, available_at=?, updated_at=? "
            "WHERE state='running' AND (claimed_at IS NULL OR claimed_at < ?)",
            (_now(), _now(), cutoff),
        )
        if n:
            self.db.log_event("warn", "tasks", f"捞回 {n} 个卡住的 running 任务")
        return n

    def stats(self) -> dict[str, Any]:
        rows = self.db.query("SELECT state, COUNT(*) c FROM tasks GROUP BY state")
        out = {r["state"]: r["c"] for r in rows}
        for key in ("pending", "running", "done", "failed", "blocked"):
            out.setdefault(key, 0)
        out["ready"] = self.db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE state='pending' AND available_at<=?", (_now(),), default=0
        )
        return out

    def list(self, *, limit: int = 50, state: str | None = None) -> list[dict[str, Any]]:
        if state:
            rows = self.db.query(
                "SELECT * FROM tasks WHERE state=? ORDER BY updated_at DESC LIMIT ?", (state, limit)
            )
        else:
            rows = self.db.query("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


# ── 通知流采集记录（完整性证据）────────────────────────────


class NoticeRuns:
    """每跑一轮通知流采集记一行。

    存在意义：如果假设「网页能看到完整名单」，就必须能回答
    "这次到底拿全了没有"。reached_end=1 才是拿全了的证据。
    """

    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        *,
        tier: str,
        url: str,
        rounds: int,
        captured: int,
        edges_seen: int,
        new_edges: int,
        distinct_likers: int,
        reached_end: bool,
        stop_reason: str,
        raw_ids: list[int] | None = None,
    ) -> int:
        self.db.execute(
            "INSERT INTO notice_runs (started_at, finished_at, tier, url, rounds, captured, "
            "edges_seen, new_edges, distinct_likers, reached_end, stop_reason, raw_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                iso(), iso(), tier, truncate(url, 500), int(rounds), int(captured),
                int(edges_seen), int(new_edges), int(distinct_likers),
                1 if reached_end else 0, truncate(stop_reason, 200),
                ",".join(str(r) for r in (raw_ids or [])),
            ),
        )
        return int(self.db.scalar("SELECT last_insert_rowid()", default=0))

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.db.rows_as_dicts(
            "SELECT * FROM notice_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        )

    def coverage(self) -> dict[str, Any]:
        """完整性概览。这是"名单是不是完整的"的答案。"""
        last = self.db.query_one("SELECT * FROM notice_runs ORDER BY started_at DESC LIMIT 1")
        total_runs = int(self.db.scalar("SELECT COUNT(*) FROM notice_runs", default=0))
        ended_runs = int(self.db.scalar(
            "SELECT COUNT(*) FROM notice_runs WHERE reached_end = 1", default=0
        ))
        edges = int(self.db.scalar("SELECT COUNT(*) FROM like_edges", default=0))
        return {
            "runs_total": total_runs,
            "runs_reached_end": ended_runs,
            "last_run": dict(last) if last else None,
            "distinct_likers": int(self.db.scalar(
                "SELECT COUNT(DISTINCT sec_uid) FROM like_edges", default=0
            )),
            "like_edges": edges,
            "replayed_only": edges > 0 and total_runs == 0,
            "verdict": self._verdict(total_runs, ended_runs, last, edges),
        }

    @staticmethod
    def _verdict(total_runs: int, ended_runs: int, last, edges: int) -> str:
        if total_runs == 0:
            if edges > 0:
                # 数据是 replay 回放来的，没经过实时采集，不能说"完整"
                return (
                    f"已有 {edges} 条点赞边，但全部来自归档回放，"
                    f"从未实时采集过 —— 完整性未经验证"
                )
            return "还没跑过通知流采集"
        if last is not None and not int(last["reached_end"]):
            return f"最后一次没有触底（{last['stop_reason']}），名单可能不完整"
        if ended_runs == 0:
            return "从未触底过，名单完整性未经验证"
        return "最近一次已触底，名单可视为完整"


# ── 大模型分析结果 ───────────────────────────────────────────


class LLMResults:
    """AI 分析结果的存取。

    按 (主体, 任务, prompt 版本, 输入哈希) 去重：
    - 输入没变 → 直接复用，不重复花钱
    - 输入变了、prompt 改了、模型换了 → 自然产生新记录，可对比
    """

    def __init__(self, db: Database):
        self.db = db

    def find(
        self, subject_kind: str, subject_id: str, task: str,
        prompt_version: str, input_digest: str,
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM llm_results WHERE subject_kind=? AND subject_id=? AND task=? "
            "AND prompt_version=? AND input_digest=?",
            (subject_kind, subject_id, task, prompt_version, input_digest),
        )
        return dict(row) if row else None

    def save(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        task: str,
        prompt_version: str,
        model: str,
        input_digest: str,
        input_summary: str,
        output_json: str,
        raw_text: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        now = _now()
        self.db.upsert(
            "llm_results",
            ("subject_kind", "subject_id", "task", "prompt_version", "input_digest"),
            {
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "task": task,
                "prompt_version": prompt_version,
                "model": model,
                "input_digest": input_digest,
                "input_summary": input_summary,
                "output_json": output_json,
                "raw_text": raw_text,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "duration_ms": duration_ms,
                "created_at": now,
                "updated_at": now,
            },
        )

    def latest(self, subject_kind: str, subject_id: str, task: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM llm_results WHERE subject_kind=? AND subject_id=? AND task=? "
            "ORDER BY created_at DESC LIMIT 1",
            (subject_kind, subject_id, task),
        )
        return dict(row) if row else None

    def all_latest(self, task: str = "profile") -> list[dict[str, Any]]:
        return self.db.rows_as_dicts(
            "SELECT * FROM v_llm_latest WHERE task=? ORDER BY created_at DESC", (task,)
        )

    def stats(self) -> dict[str, Any]:
        return {
            "count": self.db.scalar("SELECT COUNT(*) FROM llm_results", default=0),
            "prompt_tokens": self.db.scalar(
                "SELECT COALESCE(SUM(prompt_tokens),0) FROM llm_results", default=0
            ),
            "completion_tokens": self.db.scalar(
                "SELECT COALESCE(SUM(completion_tokens),0) FROM llm_results", default=0
            ),
        }


# ── 游标 ─────────────────────────────────────────────────────


class Cursors:
    def __init__(self, db: Database):
        self.db = db

    def get(self, name: str, default: str = "") -> str:
        row = self.db.query_one("SELECT cursor FROM cursor_state WHERE name=?", (name,))
        return row["cursor"] if row else default

    def set(self, name: str, cursor: str) -> None:
        self.db.upsert(
            "cursor_state", ("name",), {"name": name, "cursor": cursor, "updated_at": _now()}
        )

    def all(self) -> list[dict[str, Any]]:
        return self.db.rows_as_dicts("SELECT * FROM cursor_state ORDER BY name")
