"""热榜快照：每次抓取存一份，支持最新榜单与单词排名历史。"""
from __future__ import annotations

from typing import Any, Iterable

from ..util import iso
from ..db.connect import Database


class HotTopics:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _clean_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def save_snapshot(self, words: Iterable[dict[str, Any]], *, tier: str = "",
                      raw_blob_id: int | None = None, source: str = "douyin",
                      fetched_at: str | None = None) -> int | None:
        """写入一份榜单快照；空列表返回 None（不存空快照）。"""
        rows = []
        for rank, item in enumerate(list(words), 1):
            word = str(item.get("word") or item.get("sentence") or "").strip()
            if not word:
                continue
            rows.append((rank, word[:120],
                         self._clean_int(item.get("hot_value") or item.get("heat") or item.get("hot_score")),
                         str(item.get("sentence_id") or "") or None,
                         str(item.get("label") or "") or None))
        if not rows:
            return None
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO hot_snapshots (fetched_at, tier, source, raw_blob_id, item_count) "
                "VALUES (?,?,?,?,?)",
                (fetched_at or iso(), tier, source, raw_blob_id, len(rows)))
            snapshot_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO hot_entries (snapshot_id, rank, word, hot_value, sentence_id, label) "
                "VALUES (?,?,?,?,?,?)",
                [(snapshot_id, *row) for row in rows])
        return snapshot_id

    def latest(self, limit: int = 20, source: str | None = "douyin") -> dict[str, Any] | None:
        """最近一份快照；没有则返回 None。

        source 用来隔离数据口径：不同来源（官方接口 / 第三方镜像）的榜单
        精度与采集时点不同，混在一起做趋势会得出错误结论，所以默认只看自采。
        """
        if source:
            row = self.db.query_one(
                "SELECT id, fetched_at, tier, source, item_count FROM hot_snapshots "
                "WHERE source=? ORDER BY id DESC LIMIT 1", (source,))
        else:
            row = self.db.query_one(
                "SELECT id, fetched_at, tier, source, item_count FROM hot_snapshots "
                "ORDER BY id DESC LIMIT 1")
        if row is None:
            return None
        items = self.db.rows_as_dicts(
            "SELECT rank, word, hot_value, sentence_id, label FROM hot_entries "
            "WHERE snapshot_id=? ORDER BY rank LIMIT ?", (row["id"], max(1, limit)))
        return {"id": row["id"], "fetched_at": row["fetched_at"], "tier": row["tier"],
                "source": row["source"], "items": items}

    def sources(self) -> list[dict[str, Any]]:
        """各来源的快照数与最近采集时间（用于说明口径、避免混算）。"""
        return self.db.rows_as_dicts(
            "SELECT source, COUNT(*) AS snapshots, MAX(fetched_at) AS latest_at "
            "FROM hot_snapshots GROUP BY source ORDER BY MAX(id) DESC")

    def history(self, word: str, limit: int = 10) -> list[dict[str, Any]]:
        """某个话题最近几次上榜的排名（最新在前），用于看升降。"""
        return self.db.rows_as_dicts(
            "SELECT s.fetched_at, e.rank, e.hot_value FROM hot_entries e "
            "JOIN hot_snapshots s ON s.id = e.snapshot_id "
            "WHERE e.word=? ORDER BY s.id DESC LIMIT ?", (str(word), max(1, limit)))


class HotVideoLinks:
    """热搜词条关联的视频（代表视频 + 相关视频）。"""

    def __init__(self, db: Database):
        self.db = db

    def replace(self, sentence_id: str, aweme_ids: Iterable[str], *, fetched_at: str | None = None) -> int:
        sid = str(sentence_id or "").strip()
        ids = [str(item).strip() for item in aweme_ids if str(item or "").strip()]
        if not sid or not ids:
            return 0
        stamp = fetched_at or iso()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM hot_video_links WHERE sentence_id = ?", (sid,))
            conn.executemany(
                "INSERT OR IGNORE INTO hot_video_links (sentence_id, aweme_id, rank, fetched_at) "
                "VALUES (?,?,?,?)",
                [(sid, aweme_id, rank, stamp) for rank, aweme_id in enumerate(ids)])
        return len(ids)

    def listing(self, sentence_id: str, limit: int = 8) -> list[dict[str, Any]]:
        return self.db.rows_as_dicts(
            "SELECT w.aweme_id, w.description, w.author_sec_uid, w.cover_url, w.digg_count,"
            " w.play_count, w.comment_count, w.create_time, w.media_type, l.rank, l.fetched_at"
            " FROM hot_video_links l JOIN works w ON w.aweme_id = l.aweme_id"
            " WHERE l.sentence_id = ? ORDER BY l.rank ASC LIMIT ?",
            (str(sentence_id or "").strip(), max(1, limit)))

    def fetched_at(self, sentence_id: str) -> str:
        value = self.db.scalar(
            "SELECT MAX(fetched_at) FROM hot_video_links WHERE sentence_id = ?",
            (str(sentence_id or "").strip(),), default="")
        return str(value or "")
