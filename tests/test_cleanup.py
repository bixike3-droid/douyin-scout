"""数据保留与清理测试。

**为什么要专门测这个**

清理是**破坏性操作**，而且症状是"数据不见了"——等你发现时已经晚了。
而且这类 bug 有个特点：**用真实数据测不出来**，因为真实数据都是最近采的，
没有任何东西超期，跑一遍只会显示"没有需要清理的内容"。

所以这些测试**人为造出过期数据**（把时间戳往回拨），
才能真正走进删除路径。这是唯一确定的做法，不用等一天。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scout.store.cleanup import archive_stats, plan_cleanup, run_cleanup


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_old_blob(ctx, *, days_ago: int = 30, size: int = 4096, name: str = "old.json"):
    """造一个 N 天前的归档（含真实文件）。"""
    d = ctx.paths.raw_dir / "2020-01-01"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(b"x" * size)
    ts = _ago(days_ago)
    ctx.db.execute(
        "INSERT INTO raw_blobs (sha256, path, url, tier, content_type, byte_size,"
        " collected_at, source, note) VALUES (?,?,?,?,?,?,?,?,?)",
        (f"sha-{name}", str(f.relative_to(ctx.paths.root)), "https://x/y", "a",
         "application/json", size, ts, "test", ""),
    )
    return f


# ── 归档正文 ────────────────────────────────────────────────


def test_plan_finds_expired_archives(ctx):
    _make_old_blob(ctx, days_ago=30)
    _make_old_blob(ctx, days_ago=30, name="old2.json")
    plan = plan_cleanup(ctx, raw_days=7)
    assert plan.raw_rows == 2
    assert plan.raw_files == 2
    assert plan.raw_bytes == 8192


def test_fresh_archives_are_kept(ctx):
    _make_old_blob(ctx, days_ago=1)
    plan = plan_cleanup(ctx, raw_days=7)
    assert plan.raw_rows == 0, "1 天前的数据不该被 7 天策略清掉"


def test_zero_days_means_never_clean(ctx):
    """0 = 永不清理，不是"全删"。这个语义容易搞反。"""
    _make_old_blob(ctx, days_ago=999)
    plan = plan_cleanup(ctx, raw_days=0)
    assert plan.raw_rows == 0


def test_dry_run_changes_nothing(ctx):
    f = _make_old_blob(ctx, days_ago=30)
    plan = plan_cleanup(ctx, raw_days=7)
    result = run_cleanup(ctx, plan, dry_run=True)

    assert f.is_file(), "dry-run 绝不能删文件"
    assert result["files_deleted"] == 1, "但报告里要说清楚会删几个"
    row = ctx.db.query_one("SELECT path, pruned_at FROM raw_blobs WHERE sha256='sha-old.json'")
    assert row["path"], "dry-run 不该清空路径字段"
    assert not row["pruned_at"]


def test_apply_deletes_body_but_keeps_metadata(ctx):
    """**核心取舍**：删正文，保留元数据行。

    直接删 raw_blobs 行会让 works.raw_blob_id 变成悬空引用；
    留下元数据（sha256/url/byte_size）则"曾经采过什么"仍可追溯。
    """
    f = _make_old_blob(ctx, days_ago=30, size=5000)
    plan = plan_cleanup(ctx, raw_days=7)
    result = run_cleanup(ctx, plan, dry_run=False)

    assert not f.exists(), "正文应该被删了"
    assert result["bytes_freed"] == 5000

    row = ctx.db.query_one(
        "SELECT sha256, url, byte_size, path, pruned_at, pruned_bytes FROM raw_blobs "
        "WHERE sha256='sha-old.json'"
    )
    assert row is not None, "元数据行必须留着"
    assert row["sha256"] == "sha-old.json"
    assert row["url"] == "https://x/y"
    assert row["byte_size"] == 5000
    assert row["pruned_at"], "必须打上清理时间"
    assert row["pruned_bytes"] == 5000
    assert row["path"] == "", "路径要清空，免得后面有人拿它去找文件"


def test_already_pruned_rows_are_not_reprocessed(ctx):
    _make_old_blob(ctx, days_ago=30)
    run_cleanup(ctx, plan_cleanup(ctx, raw_days=7), dry_run=False)
    plan2 = plan_cleanup(ctx, raw_days=7)
    assert plan2.raw_rows == 0, "已经清过的不能再算一次"


def test_missing_file_is_tolerated(ctx):
    """元数据在、文件已被人手动删了 —— 不能因此崩掉。"""
    f = _make_old_blob(ctx, days_ago=30)
    f.unlink()
    result = run_cleanup(ctx, plan_cleanup(ctx, raw_days=7), dry_run=False)
    assert result["files_deleted"] == 0
    assert result["raw_marked"] == 1


# ── 点赞边（只标记不删）──────────────────────────────────────


def test_stale_edges_are_marked_not_deleted(ctx):
    """**只标记不删除。**

    可能是接口偶发返回不全，删了就找不回来。
    标记成 is_stale 让上层自己决定怎么用。
    """
    ctx.like_edges.add_many(
        [{"sec_uid": "S1", "aweme_id": "A1", "notice_id": "n1", "notice_kind": "digg"}],
        tier="a",
    )
    ctx.db.execute(
        "UPDATE like_edges SET discovered_at=?, last_confirmed_at=? WHERE sec_uid='S1'",
        (_ago(60), _ago(60)),
    )

    plan = plan_cleanup(ctx, edge_days=30)
    assert plan.unconfirmed_edges == 1

    run_cleanup(ctx, plan, dry_run=False)
    row = ctx.db.query_one("SELECT * FROM like_edges WHERE sec_uid='S1'")
    assert row is not None, "绝不能删除，只能标记"
    assert row["is_stale"] == 1


def test_recently_confirmed_edges_stay_fresh(ctx):
    ctx.like_edges.add_many(
        [{"sec_uid": "S2", "aweme_id": "A2", "notice_id": "n2", "notice_kind": "digg"}],
        tier="a",
    )
    ctx.db.execute(
        "UPDATE like_edges SET discovered_at=?, last_confirmed_at=? WHERE sec_uid='S2'",
        (_ago(60), _ago(1)),
    )
    plan = plan_cleanup(ctx, edge_days=30)
    assert plan.unconfirmed_edges == 0, "刚确认过的不能算陈旧"


def test_backfill_prevents_false_stale_signal(ctx):
    """回归测试：加字段时不能把所有历史数据判成陈旧。

    0006 给 like_edges 加了 last_confirmed_at（默认空），
    0007 把历史数据回填成 discovered_at。
    不这样做，第一次清理会把**全部**点赞边标成陈旧 ——
    假信号比没有信号更糟，因为人会开始无视它。
    """
    ctx.like_edges.add_many(
        [{"sec_uid": "S3", "aweme_id": "A3", "notice_id": "n3", "notice_kind": "digg"}],
        tier="a",
    )
    # 模拟迁移后的状态：discovered_at 有值，last_confirmed_at 被回填
    ctx.db.execute(
        "UPDATE like_edges SET discovered_at=?, last_confirmed_at=? WHERE sec_uid='S3'",
        (_ago(2), _ago(2)),
    )
    plan = plan_cleanup(ctx, edge_days=30)
    assert plan.unconfirmed_edges == 0


# ── 日志 ────────────────────────────────────────────────────


def test_old_logs_are_deleted(ctx):
    ctx.db.execute(
        "INSERT INTO request_logs (ts, tier, url, status, ok, byte_size) VALUES (?,?,?,?,?,?)",
        (_ago(60), "a", "https://x/old", 200, 1, 10),
    )
    ctx.db.execute(
        "INSERT INTO request_logs (ts, tier, url, status, ok, byte_size) VALUES (?,?,?,?,?,?)",
        (_ago(1), "a", "https://x/new", 200, 1, 10),
    )
    plan = plan_cleanup(ctx, log_days=30)
    assert plan.log_rows.get("request_logs") == 1

    run_cleanup(ctx, plan, dry_run=False)
    urls = [r["url"] for r in ctx.db.query("SELECT url FROM request_logs")]
    assert "https://x/old" not in urls
    assert "https://x/new" in urls


# ── 任务 ────────────────────────────────────────────────────


def test_only_done_tasks_are_deleted(ctx):
    """只删 done —— pending / failed 是"还没做完的事"，删了就丢了。"""
    ctx.tasks.enqueue("fetch_self", "self", "a")
    task = ctx.tasks.claim("a", limit=1)[0]
    ctx.tasks.complete(task["id"])
    ctx.db.execute("UPDATE tasks SET finished_at=?, updated_at=? WHERE id=?",
                   (_ago(60), _ago(60), task["id"]))

    ctx.tasks.enqueue("fetch_likers", "AWEME_PENDING", "a")

    plan = plan_cleanup(ctx, task_days=14)
    assert plan.task_rows == 1

    run_cleanup(ctx, plan, dry_run=False)
    left = ctx.db.rows_as_dicts("SELECT kind, target, state FROM tasks")
    assert all(r["state"] != "done" for r in left)
    assert any(r["target"] == "AWEME_PENDING" for r in left), "pending 的必须留着"


# ── 汇总 ────────────────────────────────────────────────────


def test_archive_stats_reports_disk_usage(ctx):
    _make_old_blob(ctx, size=2048)
    stats = archive_stats(ctx)
    assert stats["rows"] == 1
    assert stats["disk_bytes"] == 2048
    assert stats["disk_files"] == 1
    assert stats["retention_days"] >= 0
    assert any(d["files"] == 1 for d in stats["days"])


def test_plan_to_dict_is_serializable(ctx):
    import json

    _make_old_blob(ctx, days_ago=30)
    plan = plan_cleanup(ctx, raw_days=7)
    json.dumps(plan.to_dict())   # 面板要把它转 JSON
