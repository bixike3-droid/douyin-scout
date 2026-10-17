"""洞察/企业类工具：趋势、作品详情、历史报告、指标补录、评论采集。"""
import asyncio
import json
import time

from scout.store.enterprise import EnterpriseStore
from scout.tools import registry


def _run(ctx, tool_id, agent, args, confirm=None):
    return asyncio.run(registry.execute(ctx, tool_id, agent, args, confirm=confirm))


def _work(ctx, aweme_id, *, days_ago, play=0, digg=0, comment=0, mine=True, desc=""):
    ctx.works.upsert({"aweme_id": aweme_id, "description": desc or aweme_id,
                      "create_time": int(time.time()) - days_ago * 86400,
                      "play_count": play, "digg_count": digg, "comment_count": comment,
                      "is_mine": 1 if mine else 0})


def test_new_tools_registered_with_permissions():
    assert {"analytics_trend", "work_detail", "report_read",
            "metrics_backfill", "collect_comments"} <= set(registry.REGISTRY)
    assert registry.allows(registry.REGISTRY["work_detail"], "audience")
    assert not registry.allows(registry.REGISTRY["analytics_trend"], "audience")
    assert registry.REGISTRY["metrics_backfill"].level == "confirm"
    assert registry.REGISTRY["collect_comments"].level == "confirm"
    assert registry.REGISTRY["report_read"].level == "read"


def test_analytics_trend_compares_two_windows(ctx):
    _work(ctx, "w-new-1", days_ago=3, play=120, desc="新作品A")
    _work(ctx, "w-new-2", days_ago=9, play=80, desc="新作品B")
    _work(ctx, "w-old", days_ago=45, play=50, desc="旧作品")
    result = _run(ctx, "analytics_trend", "content", {"days": 30, "metric": "play_count"})
    assert result["ok"] is True
    assert result["data"]["recent"] == 2 and result["data"]["previous"] == 1
    assert result["data"]["recent_total"] == 200 and result["data"]["previous_total"] == 50
    assert "+300.0%" in result["content"]
    assert "新作品A" in result["content"]


def test_analytics_trend_without_data_is_explicit(ctx):
    result = _run(ctx, "analytics_trend", "review", {"days": 7})
    assert result["ok"] is False and "采集" in result["summary"]


def test_work_detail_aggregates_local_evidence(ctx):
    _work(ctx, "w1", days_ago=2, play=1000, digg=30, comment=2, desc="测试作品")
    ctx.like_edges.add_many([{"sec_uid": "u1", "aweme_id": "w1", "notice_id": "n1"},
                             {"sec_uid": "u2", "aweme_id": "w1", "notice_id": "n2"}])
    ctx.comments.upsert_many([
        {"comment_id": "c1", "aweme_id": "w1", "text": "好想吃", "digg_count": 9},
        {"comment_id": "c2", "aweme_id": "w1", "text": "在哪", "digg_count": 3}])
    result = _run(ctx, "work_detail", "audience", {"aweme_id": "w1"})
    assert result["ok"] is True
    assert result["data"] == {"aweme_id": "w1", "likers": 2, "comments": 2}
    assert "好想吃" in result["content"] and "点赞人 2 人" in result["content"]


def test_work_detail_defaults_to_latest_mine_work(ctx):
    _work(ctx, "old", days_ago=30, desc="旧")
    _work(ctx, "new", days_ago=1, desc="最新一条")
    result = _run(ctx, "work_detail", "content", {})
    assert result["data"]["aweme_id"] == "new" and "最新一条" in result["content"]


def _insert_report(ctx, text="主推周边游"):
    output = {"strategy": [{"text": text, "evidence_ids": ["E1"]}],
              "topics": [{"title": "一日游路线"}],
              "diagnosis": [{"text": "账号人设不清晰"}],
              "optimization": [{"text": "统一封面风格"}]}
    evidence = {"evidence": [{"data": {"request": "竹梦村周末引流"}}]}
    ctx.db.execute(
        "INSERT INTO enterprise_reports(created_at,prompt_version,system_prompt,model,input_digest,"
        "input_json,output_json,prompt_tokens,completion_tokens,duration_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("2026-10-16T10:00:00Z", "v1", "sys", "deepseek-flash", "d1",
         json.dumps(evidence, ensure_ascii=False), json.dumps(output, ensure_ascii=False), 1, 1, 1))


def test_report_read_latest_and_empty(ctx):
    empty = _run(ctx, "report_read", "review", {})
    assert empty["ok"] is False and "还没有" in empty["summary"]
    _insert_report(ctx)
    result = _run(ctx, "report_read", "review", {})
    assert result["ok"] is True
    assert "主推周边游" in result["content"] and "一日游路线" in result["content"]
    missing = _run(ctx, "report_read", "review", {"report_id": 999})
    assert missing["ok"] is False and "不存在" in missing["summary"]


def test_metrics_backfill_requires_confirmation_and_writes(ctx):
    _work(ctx, "w1", days_ago=1)
    denied = _run(ctx, "metrics_backfill", "data",
                  {"aweme_id": "w1", "measured_at": "2026-10-16", "source": "后台截图", "play_count": 100})
    assert denied["ok"] is False and "确认" in denied["summary"]
    assert EnterpriseStore(ctx.db).metric_history() == []

    async def allow(spec, agent, args):
        return True

    result = _run(ctx, "metrics_backfill", "data",
                  {"aweme_id": "w1", "measured_at": "2026-10-16", "source": "后台截图",
                   "play_count": 100, "digg_count": 5}, confirm=allow)
    assert result["ok"] is True
    history = EnterpriseStore(ctx.db).metric_history()
    assert history and history[0]["play_count"] == 100 and history[0]["digg_count"] == 5
    row = ctx.db.query_one("SELECT agent,status FROM tool_calls WHERE tool='metrics_backfill' "
                           "ORDER BY id DESC LIMIT 1")
    assert row["status"] == "complete"


def test_metrics_backfill_rejects_non_mine_work(ctx):
    _work(ctx, "other", days_ago=1, mine=False)

    async def allow(spec, agent, args):
        return True

    result = _run(ctx, "metrics_backfill", "data",
                  {"aweme_id": "other", "measured_at": "2026-10-16", "source": "x", "play_count": 1},
                  confirm=allow)
    assert result["ok"] is False and "本人作品" in result["summary"]


def test_collect_comments_needs_login(ctx, monkeypatch):
    from scout.desktop import actions

    _work(ctx, "w1", days_ago=1)
    monkeypatch.setattr(actions, "login_status", lambda paths: {"saved": False, "tier": "a", "message": ""})

    async def allow(spec, agent, args):
        return True

    result = _run(ctx, "collect_comments", "data", {"aweme_id": "w1"}, confirm=allow)
    assert result["ok"] is False and "登录" in result["summary"]


def test_collect_comments_reports_count(ctx, monkeypatch):
    from scout.collect import comments_run
    from scout.desktop import actions

    monkeypatch.setattr(actions, "login_status", lambda paths: {"saved": True, "tier": "a", "message": ""})

    async def fake(ctx_, emit, aweme_id):
        assert aweme_id == "w1"
        emit({"message": "采集到 1 页"})
        return {"aweme_id": aweme_id, "items": 12, "state": "sampled"}

    monkeypatch.setattr(comments_run, "collect_for_work", fake)

    async def allow(spec, agent, args):
        return True

    result = _run(ctx, "collect_comments", "data", {"aweme_id": "w1"}, confirm=allow)
    assert result["ok"] is True
    assert "12 条" in result["summary"] and "抽样" in result["summary"]
