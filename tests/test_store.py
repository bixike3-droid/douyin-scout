"""存储层测试：迁移幂等、upsert 幂等、任务队列可靠性、归档去重。"""

from __future__ import annotations

from scout.db.migrate import applied_versions, migrate, pending_versions
from scout.util import iso


def test_migrate_is_idempotent(ctx):
    assert migrate(ctx.db) == [], "二次迁移不应重复应用"
    applied = applied_versions(ctx.db)
    assert applied, "至少应应用一个迁移"
    assert 1 in applied, "初始迁移必须在其中"
    assert pending_versions(ctx.db) == [], "迁移完不应再有待应用项"


def test_late_added_columns_are_repaired_on_old_databases(tmp_path):
    """历史遗留：0025 执行完之后又被追加过列，老库不会重跑 0025，须由补列迁移修好。"""
    from scout.db.connect import Database

    def columns(db, table):
        return {row["name"] for row in db.query(f"PRAGMA table_info({table})")}

    with Database.open(tmp_path / "legacy.db") as db:
        migrate(db)
        # 还原成“已经跑过 0025、但两张表都缺列”的真实老库形态
        db.execute("ALTER TABLE conversation_branches DROP COLUMN attachment_map_json")
        db.execute("ALTER TABLE codex_sessions DROP COLUMN tools_digest")
        db.execute("DELETE FROM schema_migrations WHERE version IN (26,27)")

        assert migrate(db) == ["0026_branch_attachment_map", "0027_codex_session_tools_digest"]
        assert "attachment_map_json" in columns(db, "conversation_branches")
        assert "tools_digest" in columns(db, "codex_sessions")
        assert migrate(db) == [], "补完列之后不应再有待应用项"


def test_users_upsert_is_idempotent_and_merges(ctx):
    ctx.users.upsert({"sec_uid": "SEC1", "nickname": "张三"})
    ctx.users.upsert({"sec_uid": "SEC1", "nickname": "张三改", "follower_count": 1200})

    rows = ctx.users.list(limit=10)
    assert len(rows) == 1, "同一 sec_uid 只能有一行"
    assert rows[0]["nickname"] == "张三改"
    assert rows[0]["follower_count"] == 1200


def test_users_upsert_ignores_missing_fields(ctx):
    ctx.users.upsert({"sec_uid": "SEC2", "nickname": "甲", "signature": "签名"})
    ctx.users.upsert({"sec_uid": "SEC2", "nickname": "甲2"})
    row = ctx.users.get("SEC2")
    assert row["signature"] == "签名", "未提供的字段必须保持原值"


def test_like_edges_dedup(ctx):
    edges = [{"sec_uid": "SEC1", "aweme_id": "111", "notice_id": "n1"}]
    assert ctx.like_edges.add_many(edges) == 1
    assert ctx.like_edges.add_many(edges) == 0, "重复点赞边不应重复入库"

    more = edges + [{"sec_uid": "SEC2", "aweme_id": "111", "notice_id": "n2"}]
    assert ctx.like_edges.add_many(more) == 1


def test_like_edges_empty_ids_still_distinct(ctx):
    """空串占位而非 NULL：否则 SQLite 的 UNIQUE 会失效。"""
    ctx.like_edges.add_many([{"sec_uid": "SECX", "aweme_id": "", "notice_id": ""}])
    ctx.like_edges.add_many([{"sec_uid": "SECX", "aweme_id": "", "notice_id": ""}])
    assert ctx.like_edges.stats()["total"] == 1


def test_works_upsert_and_stats(ctx):
    ctx.works.upsert({"aweme_id": "1", "description": "第一条", "digg_count": 10, "hashtags": ["a", "b"]})
    ctx.works.upsert({"aweme_id": "1", "digg_count": 99})
    row = ctx.works.get("1")
    assert row["digg_count"] == 99
    assert row["description"] == "第一条"
    assert "a" in row["hashtags_json"]


def test_snapshot_keeps_one_row_per_day(ctx):
    ctx.snapshots.record("SEC1", {"follower_count": 100}, day="2026-10-01")
    ctx.snapshots.record("SEC1", {"follower_count": 150}, day="2026-10-01")
    ctx.snapshots.record("SEC1", {"follower_count": 200}, day="2026-10-02")
    history = ctx.snapshots.history("SEC1")
    assert len(history) == 2
    assert history[0]["follower_count"] == 200, "同一天应更新而不是新增"


def test_task_lifecycle(ctx):
    assert ctx.tasks.enqueue("fetch_profile", "SEC1", "b") is True
    assert ctx.tasks.enqueue("fetch_profile", "SEC1", "b") is False, "同一任务不应重复入队"

    claimed = ctx.tasks.claim("b", limit=1)
    assert len(claimed) == 1
    assert claimed[0]["attempts"] == 1, "领取即计一次尝试"
    assert ctx.tasks.claim("b", limit=1) == [], "已被领取的任务不应再被领到"

    ctx.tasks.complete(claimed[0]["id"])
    assert ctx.tasks.stats()["done"] == 1


def test_task_fail_backoff_then_exhaust(ctx):
    ctx.tasks.enqueue("fetch_profile", "SEC2", "b", max_attempts=2)
    task = ctx.tasks.claim("b", limit=1)[0]
    assert ctx.tasks.fail(task["id"], "boom") == "retry"
    row = ctx.db.query_one("SELECT state, available_at FROM tasks WHERE id=?", (task["id"],))
    assert row["state"] == "pending"
    assert row["available_at"] > iso()[:19] or row["available_at"] > iso()[:13], "应有退避延迟"

    # 手动清零可用时间后再次领取
    ctx.db.execute("UPDATE tasks SET available_at=? WHERE id=?", (iso(), task["id"]))
    second = ctx.tasks.claim("b", limit=1)[0]
    assert ctx.tasks.fail(second["id"], "boom again") == "failed"


def test_reclaim_stuck_tasks(ctx):
    ctx.tasks.enqueue("fetch_profile", "SEC3", "b")
    ctx.tasks.claim("b", limit=1)
    # 模拟进程崩溃：claimed_at 变成很久以前
    ctx.db.execute("UPDATE tasks SET claimed_at='2020-01-01T00:00:00Z' WHERE target='SEC3'")
    assert ctx.tasks.reclaim_stuck(older_than_minutes=30) == 1
    assert ctx.tasks.stats()["pending"] == 1


def test_raw_archive_dedup(ctx):
    payload = '{"a":1}'
    first = ctx.archive.save(payload, url="https://x.test/a", content_type="application/json")
    second = ctx.archive.save(payload, url="https://x.test/a", content_type="application/json")
    assert first.deduped is False
    assert second.deduped is True
    assert second.id == first.id
    assert ctx.archive.stats()["count"] == 1
    assert ctx.archive.load_text(first.id) == payload


def test_raw_archive_oversize_records_metadata_only(ctx):
    ctx.archive.max_bytes = 8
    ref = ctx.archive.save(b"x" * 100, url="https://x.test/big")
    assert ref.stored is False
    assert ctx.archive.get(ref.id)["path"] == ""
    assert ctx.archive.stats()["metadata_only"] == 1


def test_cache_ttl_and_purge(ctx):
    ctx.cache.set("k1", {"v": 1}, expire_seconds=3600)
    assert ctx.cache.get("k1") == {"v": 1}

    # 注意：get 命中过期项会顺手删掉，所以这里不先读，专门验证 purge
    ctx.cache.set("k2", {"v": 2}, expire_seconds=-1)
    assert ctx.cache.purge_expired() >= 1
    assert ctx.cache.get("k2") is None

    ctx.cache.set("k3", {"v": 3}, expire_seconds=-1)
    assert ctx.cache.get("k3") is None, "过期应读不到"
    assert ctx.cache.stats()["entries"] >= 1
