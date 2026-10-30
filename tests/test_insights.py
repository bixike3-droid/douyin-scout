"""图表数据：作品周趋势、受众分布、互动活跃度。"""
from __future__ import annotations

from datetime import datetime, timedelta

from scout.store.insights import Insights
from scout.util import iso, local_tz


def test_insights_summarises_works_weeks_and_top(ctx):
    now = datetime.now(local_tz())
    ctx.works.upsert({"aweme_id": "w1", "description": "本周作品", "is_mine": 1,
                      "create_time": int(now.timestamp()), "play_count": 100, "digg_count": 10,
                      "comment_count": 3, "share_count": 1, "collect_count": 2})
    ctx.works.upsert({"aweme_id": "w2", "description": "上月作品", "is_mine": 1,
                      "create_time": int((now - timedelta(days=35)).timestamp()),
                      "play_count": 50, "digg_count": 60, "comment_count": 4})
    ctx.works.upsert({"aweme_id": "other", "description": "别人的作品", "is_mine": 0,
                      "create_time": int(now.timestamp()), "play_count": 9999})

    data = Insights(ctx.db).build(weeks=12)
    works = data["works"]
    assert works["total"] == 2
    assert works["totals"] == {"play": 150, "digg": 70, "comment": 7, "share": 1, "collect": 2}
    assert len(works["weeks"]) == 12
    assert sum(week["works"] for week in works["weeks"]) == 2
    assert works["weeks"][-1]["works"] == 1                      # 本周
    assert [item["aweme_id"] for item in works["top"]][:2] == ["w2", "w1"]
    assert works["top"][0]["digg"] == 60


def test_insights_audience_buckets_depth_and_activity(ctx):
    now = datetime.now(local_tz())
    ctx.works.upsert({"aweme_id": "w1", "description": "作品一", "is_mine": 1,
                      "create_time": int(now.timestamp())})
    ctx.works.upsert({"aweme_id": "w2", "description": "作品二", "is_mine": 1,
                      "create_time": int(now.timestamp())})
    ctx.users.upsert({"sec_uid": "SEC1", "nickname": "甲", "follower_count": 500, "profile_state": "ok"})
    ctx.users.upsert({"sec_uid": "SEC2", "nickname": "乙", "follower_count": 25_000})
    ctx.like_edges.add_many([
        {"sec_uid": "SEC1", "aweme_id": "w1", "notice_id": "n1", "discovered_at": iso(now)},
        {"sec_uid": "SEC1", "aweme_id": "w2", "notice_id": "n2", "discovered_at": iso(now)},
        {"sec_uid": "SEC2", "aweme_id": "w1", "notice_id": "n3",
         "discovered_at": iso(now - timedelta(days=5))},
    ])

    data = Insights(ctx.db).build(days=30)
    audience = data["audience"]
    assert audience["total"] == 2
    assert audience["profiled"] == 1 and audience["complete_pct"] == 50
    assert audience["edges"] == 3 and audience["per_user"] == 1.5
    buckets = {item["label"]: item["count"] for item in audience["followers"]}
    assert buckets["1 千以下"] == 1 and buckets["1 万 – 10 万"] == 1
    assert buckets["未知"] == 0
    depth = {item["label"]: item["count"] for item in audience["depth"]}
    assert depth == {"1 个": 1, "2 个": 1, "3 个以上": 0}
    assert len(audience["activity"]) == 30
    assert sum(item["count"] for item in audience["activity"]) == 3
    assert audience["activity"][-1]["count"] == 2


def test_insights_empty_database_is_zeroed(ctx):
    data = Insights(ctx.db).build()
    assert data["works"]["total"] == 0
    assert data["works"]["totals"] == {"play": 0, "digg": 0, "comment": 0, "share": 0, "collect": 0}
    assert len(data["works"]["weeks"]) == 12
    assert data["audience"]["total"] == 0 and data["audience"]["complete_pct"] == 0
    assert all(item["count"] == 0 for item in data["audience"]["activity"])
