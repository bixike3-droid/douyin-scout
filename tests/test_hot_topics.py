"""抖音热榜：接口解析、快照入库与失败回落（不联网，全部注入）。"""
import asyncio

from scout.collect.hot import HotFetchError, classify_failure, extract_words
from scout.store.hot import HotTopics
from scout.tools import hot as hot_tool


def test_classify_failure_separates_causes():
    assert classify_failure(status=2483, body=b"{}", payload={}).kind == "login_required"
    assert classify_failure(status=200, body=b"", payload=None).kind == "empty"
    assert classify_failure(status=403, body=b"denied", payload=None).kind == "http"
    assert classify_failure(status=200, body=b"<html>", payload=None).kind == "invalid_json"
    degraded = classify_failure(status=200, body=b'{"data":{}}', payload={"data": {}})
    assert degraded.kind == "degraded" and "降级" in str(degraded)
    assert isinstance(degraded, HotFetchError)


def test_snapshot_source_isolation(ctx):
    store = HotTopics(ctx.db)
    store.save_snapshot([{"word": "自采话题", "hot_value": 11_332_156}], source="douyin")
    store.save_snapshot([{"word": "镜像话题", "hot_value": 11_360_000}], source="mirror")
    assert store.latest()["items"][0]["word"] == "自采话题"      # 默认只看自采，不被镜像覆盖
    assert store.latest()["source"] == "douyin"
    assert store.latest(source="mirror")["items"][0]["word"] == "镜像话题"
    assert {item["source"] for item in store.sources()} == {"douyin", "mirror"}


def test_extract_words_tolerates_field_shapes():
    assert extract_words({"data": {"word_list": [{"word": "乡村振兴", "hot_value": 100}]}}) == \
        [{"word": "乡村振兴", "hot_value": 100}]
    assert extract_words({"data": {"trending_list": [{"sentence": "短句", "hot_value": 9}]}})[0]["sentence"] == "短句"
    assert extract_words({"data": {"list": []}}) == []
    assert extract_words({"status_code": 0}) == []


def test_snapshot_roundtrip_and_rank_history(ctx):
    store = HotTopics(ctx.db)
    store.save_snapshot([{"word": "A", "hot_value": 10}, {"word": "B", "hot_value": 9}], tier="b")
    store.save_snapshot([{"word": "B", "hot_value": 12}, {"word": "C", "hot_value": 11}], tier="a")
    latest = store.latest()
    assert [item["word"] for item in latest["items"]] == ["B", "C"]
    assert latest["items"][0]["rank"] == 1 and latest["tier"] == "a"
    history = store.history("B")
    assert [entry["rank"] for entry in history] == [1, 2]      # 最新在前：先第 2 名，后第 1 名


def test_snapshot_ignores_empty_list(ctx):
    assert HotTopics(ctx.db).save_snapshot([]) is None
    assert HotTopics(ctx.db).latest() is None


def test_hot_snapshot_service_reads_latest(ctx):
    """启动首屏：不联网，直接读最近一次快照。"""
    from scout.desktop.service import DesktopService
    HotTopics(ctx.db).save_snapshot([{"word": "乡村振兴", "hot_value": 100}], tier="b",
                                    fetched_at="2026-10-17T09:00:00+00:00")
    data = DesktopService(ctx.paths).hot_snapshot()
    assert data["topics"][0]["word"] == "乡村振兴"
    assert "本地快照" in data["note"]


def test_hot_snapshot_service_returns_none_without_history(ctx):
    from scout.desktop.service import DesktopService
    assert DesktopService(ctx.paths).hot_snapshot() is None


def test_snapshot_age_gate_avoids_duplicate_refresh():
    """启动时快照够新就不联网刷新（避免列表先显示旧快照再变一次）。"""
    from datetime import datetime, timedelta, timezone
    from scout.desktop.window import snapshot_age_minutes
    fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    assert snapshot_age_minutes(fresh) < 10
    assert snapshot_age_minutes(stale) > 60
    assert snapshot_age_minutes("not-a-time") is None


def test_hot_tool_falls_back_to_snapshot(ctx, monkeypatch):
    HotTopics(ctx.db).save_snapshot([{"word": "乡村振兴", "hot_value": 100}], tier="b",
                                    fetched_at="2026-10-17T09:00:00+00:00")

    async def broken(context):
        raise RuntimeError("验证码中间页")

    monkeypatch.setattr(hot_tool, "_douyin_hot", broken)
    result = asyncio.run(hot_tool._hot(ctx, {"limit": 5}))
    assert result["ok"] and "本地快照" in result["summary"]
    assert "乡村振兴" in result["content"]


def test_hot_tool_reports_failure_without_snapshot(ctx, monkeypatch):
    async def broken(context):
        raise RuntimeError("验证码中间页")

    monkeypatch.setattr(hot_tool, "_douyin_hot", broken)
    result = asyncio.run(hot_tool._hot(ctx, {"limit": 5}))
    assert not result["ok"] and "验证码" in result["summary"]
