"""采集结果的聚合视图：给图表用的、跨全库的统计。

页面表格按 40 条分页，图表要看全量趋势，所以统计必须留在数据库侧。
这里只读，不写库；时区跟 `app.timezone` 走。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from ..util import iso, local_tz, parse_iso, utcnow

FOLLOWER_BUCKETS = (
    ("1 千以下", 0, 1_000),
    ("1 千 – 1 万", 1_000, 10_000),
    ("1 万 – 10 万", 10_000, 100_000),
    ("10 万以上", 100_000, None),
)


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _compact_day(day: date) -> str:
    return f"{day.month}/{day.day}"


class Insights:
    def __init__(self, db, *, tz: str = "Asia/Shanghai"):
        self.db = db
        self.tz = local_tz(tz)

    def build(self, *, weeks: int = 12, days: int = 30) -> dict[str, Any]:
        return {
            "works": self._works(weeks=weeks),
            "audience": self._audience(days=days),
            "generated_at": iso(utcnow()),
        }

    # ── 作品 ────────────────────────────────────────────────

    def _works(self, *, weeks: int) -> dict[str, Any]:
        rows = self.db.rows_as_dicts(
            "SELECT aweme_id, description, create_time, play_count, digg_count, comment_count,"
            " share_count, collect_count FROM works WHERE is_mine=1 ORDER BY create_time DESC")
        columns = {"play": "play_count", "digg": "digg_count", "comment": "comment_count",
                   "share": "share_count", "collect": "collect_count"}
        totals = {key: 0 for key in columns}
        for row in rows:
            for key, column in columns.items():
                totals[key] += int(row.get(column) or 0)

        this_week = _week_start(datetime.now(self.tz).date())
        starts = [this_week - timedelta(weeks=offset) for offset in range(weeks - 1, -1, -1)]
        buckets = {start: {"works": 0, "play": 0, "digg": 0, "comment": 0} for start in starts}
        for row in rows:
            try:
                created = datetime.fromtimestamp(int(row.get("create_time") or 0), tz=self.tz).date()
            except (OSError, OverflowError, ValueError):
                continue
            start = _week_start(created)
            if start in buckets:
                bucket = buckets[start]
                bucket["works"] += 1
                bucket["play"] += int(row.get("play_count") or 0)
                bucket["digg"] += int(row.get("digg_count") or 0)
                bucket["comment"] += int(row.get("comment_count") or 0)

        top = sorted(rows, key=lambda row: int(row.get("digg_count") or 0), reverse=True)[:5]
        return {
            "total": len(rows),
            "totals": totals,
            "weeks": [{"start": start.isoformat(), "label": _compact_day(start), **buckets[start]} for start in starts],
            "top": [
                {
                    "aweme_id": str(row.get("aweme_id") or ""),
                    "description": (row.get("description") or "未命名作品")[:40],
                    "play": int(row.get("play_count") or 0),
                    "digg": int(row.get("digg_count") or 0),
                    "comment": int(row.get("comment_count") or 0),
                }
                for row in top
            ],
        }

    # ── 受众 ────────────────────────────────────────────────

    def _audience(self, *, days: int) -> dict[str, Any]:
        total = int(self.db.scalar(
            "SELECT COUNT(DISTINCT sec_uid) FROM like_edges", default=0))
        profiled = int(self.db.scalar(
            "SELECT COUNT(*) FROM users WHERE profile_fetched_at IS NOT NULL"
            " AND sec_uid IN (SELECT sec_uid FROM like_edges)", default=0))

        followers = [0] * (len(FOLLOWER_BUCKETS) + 1)  # 末位是「未知」
        for row in self.db.query(
                "SELECT u.follower_count FROM users u"
                " WHERE u.sec_uid IN (SELECT sec_uid FROM like_edges)"):
            count = row["follower_count"]
            if count is None:
                followers[-1] += 1
                continue
            value = int(count)
            for index, (_, low, high) in enumerate(FOLLOWER_BUCKETS):
                if value >= low and (high is None or value < high):
                    followers[index] += 1
                    break

        depth_counts = Counter()
        for row in self.db.query(
                "SELECT sec_uid, COUNT(DISTINCT aweme_id) AS works FROM like_edges GROUP BY sec_uid"):
            works = int(row["works"] or 0)
            depth_counts["1 个" if works <= 1 else "2 个" if works == 2 else "3 个以上"] += 1

        today = datetime.now(self.tz).date()
        horizons = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
        activity = {day: 0 for day in horizons}
        for row in self.db.query("SELECT discovered_at FROM like_edges"):
            value = row["discovered_at"]
            if not value:
                continue
            try:
                moment = parse_iso(str(value)).astimezone(self.tz).date()
            except ValueError:
                continue
            if moment in activity:
                activity[moment] += 1

        edges = int(self.db.scalar("SELECT COUNT(*) FROM like_edges", default=0))
        return {
            "total": total,
            "edges": edges,
            "per_user": round(edges / total, 1) if total else 0,
            "profiled": profiled,
            "complete_pct": round(profiled * 100 / total) if total else 0,
            "followers": [
                {"label": label, "count": followers[index]}
                for index, (label, _, _) in enumerate(FOLLOWER_BUCKETS)
            ] + [{"label": "未知", "count": followers[-1]}],
            "depth": [
                {"label": label, "count": depth_counts.get(label, 0)}
                for label in ("1 个", "2 个", "3 个以上")
            ],
            "activity": [
                {"date": day.isoformat(), "label": _compact_day(day), "count": activity[day]}
                for day in horizons
            ],
        }
