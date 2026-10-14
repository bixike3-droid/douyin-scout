"""Enterprise decisions: scope, sources, unknown metrics, cache and human review."""
import asyncio
import copy
import json
from dataclasses import replace

import pytest

from scout.analyze.enterprise import build_input, generate, render_output, export_report
from scout.llm import LLMReply, LLMError
from scout.store.enterprise import EnterpriseStore, DEFAULT_PROFILE
from scout.parse.extract import normalize_work


def brief(**changes):
    return {**DEFAULT_PROFILE, "features": "测试资料：竹林与农耕体验", "offer": "测试产品：周末农耕体验，价格未知",
            "source": "模拟运营方资料，仅用于软件测试", **changes}


def reply_data(ref="E1"):
    return {"summary": "测试报告：缺少实际引流数据，以下为待验证建议。",
        "diagnosis": [{"text": "仅凭作品互动不能证明到店效果", "evidence_ids": [ref]}],
        "optimization": [{"text": "拍摄并核实体验内容与预约信息", "evidence_ids": [ref]}],
        "topics": [{"title": "周末农耕体验说明", "platform": "抖音", "hook": "周末能体验哪些农事？",
                    "outline": "实拍目前提供的体验", "cta": "预约渠道待确认", "evidence_ids": [ref], "needs_confirmation": "价格、时间、预约方式"}],
        "strategy": [{"text": "先核实产品，再安排一次内容测试", "evidence_ids": [ref]}],
        "measurement": ["记录实际咨询及来源，不能将播放直接视为客户"], "unknowns": ["未获得预约及到店记录"]}


class FakeClient:
    def __init__(self, output=None):
        self.output = output or reply_data()
        self.calls = []

    async def chat(self, system, user, **kwargs):
        self.calls.append((system, json.loads(user)))
        return LLMReply(text=json.dumps(self.output, ensure_ascii=False), model="test-actual-model", prompt_tokens=17, completion_tokens=31, duration_ms=5)


def add_work(ctx, identifier="mine", mine=True):
    ctx.works.upsert({"aweme_id": identifier, "is_mine": int(mine), "description": "测试体验内容",
                      "digg_count": 9, "comment_count": 2})


def metric(identifier="mine", **changes):
    return {"aweme_id": identifier, "source": "测试后台截图", "measured_at": "2026-10-10", "play_count": 0, **changes}


def test_unconfirmed_account_never_enters_enterprise_analysis(ctx):
    store = EnterpriseStore(ctx.db)
    add_work(ctx)
    add_work(ctx, "foreign", False)
    ctx.users.upsert({"sec_uid": "private-user", "nickname": "不应发送的互动者", "signature": "private"})
    store.save_profile(brief())
    assert [e["id"] for e in build_input(ctx)["evidence"]] == ["E1"]
    store.save_profile(brief(account_confirmed=True))
    data = build_input(ctx)
    assert len(data["evidence"]) == 2
    assert data["evidence"][1]["data"]["aweme_id"] == "mine"
    assert data["evidence"][1]["data"]["metrics"]["play_count"] is None
    assert "private-user" not in json.dumps(data) and "foreign" not in json.dumps(data)


def test_metrics_are_sourced_zero_is_real_and_raw_stats_are_preserved(ctx):
    store = EnterpriseStore(ctx.db)
    add_work(ctx)
    store.save_metrics(metric(digg_count=0, notes="测试脚本摘要"))
    row = store.works()[0]
    assert row["play_count"] == row["digg_count"] == 0
    assert row["comment_count"] == 2
    assert row["metric_sources"]["play_count"]["measured_at"] == "2026-10-10"
    assert "人工补录" in row["metric_sources"]["play_count"]["source"]
    assert row["content_notes"] == "测试脚本摘要"
    raw = dict(ctx.db.query_one("SELECT * FROM works WHERE aweme_id='mine'"))
    assert raw["digg_count"] == 9 and raw["play_count"] is None
    store.save_metrics(metric(play_count=123, measured_at="2026-10-09"))
    assert store.works()[0]["play_count"] == 0  # chronological latest, not insertion latest
    assert len(store.metric_history()) == 2


@pytest.mark.parametrize("changes", [{"play_count": -1}, {"play_count": True}, {"play_count": 2.5},
    {"play_count": None}, {"source": ""}, {"measured_at": "bad"}, {"measured_at": "2099-01-01"}])
def test_invalid_metric_snapshot_does_not_change_database(ctx, changes):
    add_work(ctx)
    with pytest.raises(ValueError):
        EnterpriseStore(ctx.db).save_metrics(metric(**changes))
    assert ctx.db.scalar("SELECT COUNT(*) FROM enterprise_metrics") == 0


def test_other_authors_cannot_receive_manual_metrics(ctx):
    add_work(ctx, "foreign", False)
    with pytest.raises(ValueError):
        EnterpriseStore(ctx.db).save_metrics(metric("foreign"))


def test_missing_business_details_stop_before_paid_call(ctx):
    client = FakeClient()
    with pytest.raises(ValueError, match="企业特色"):
        asyncio.run(generate(ctx, client))
    assert not client.calls


def test_report_cache_tracks_enterprise_feedback_metrics_and_requested_model(ctx):
    store, client = EnterpriseStore(ctx.db), FakeClient()
    add_work(ctx)
    store.save_profile(brief(account_confirmed=True))
    first = asyncio.run(generate(ctx, client))
    assert asyncio.run(generate(ctx, client))["cached"]
    assert len(client.calls) == 1
    store.save_profile(brief(account_confirmed=True, feedback="模拟执行反馈：未获得预约数据", baseline_report_id=first["report_id"]))
    second = asyncio.run(generate(ctx, client))
    store.save_metrics(metric(play_count=100))
    third = asyncio.run(generate(ctx, client))
    ctx.config = replace(ctx.config, llm=replace(ctx.config.llm, model="different-model"))
    fourth = asyncio.run(generate(ctx, client))
    assert len({r["report_id"] for r in (first, second, third, fourth)}) == 4
    original = store.report(first["report_id"])
    assert original["model"] == "test-actual-model"
    assert "E2" not in {e["id"] for e in original["input"]["evidence"]}
    assert original["input"]["evidence"][1]["data"]["metrics"]["play_count"] is None


@pytest.mark.parametrize("failure", ["bad_ref", "missing_field", "wrong_shape"])
def test_invalid_model_output_is_rejected_without_report(ctx, failure):
    EnterpriseStore(ctx.db).save_profile(brief())
    output = reply_data()
    if failure == "bad_ref":
        output["topics"][0]["evidence_ids"] = ["W999"]
    elif failure == "missing_field":
        del output["topics"][0]["outline"]
    else:
        output["diagnosis"] = "bad"
    with pytest.raises(ValueError):
        asyncio.run(generate(ctx, FakeClient(output)))
    assert ctx.db.scalar("SELECT COUNT(*) FROM enterprise_reports") == 0


def test_provider_failure_does_not_create_report(ctx):
    EnterpriseStore(ctx.db).save_profile(brief())
    class Failed:
        async def chat(self, *args, **kwargs):
            raise LLMError("test timeout")
    with pytest.raises(LLMError):
        asyncio.run(generate(ctx, Failed()))
    assert ctx.db.scalar("SELECT COUNT(*) FROM enterprise_reports") == 0


def test_human_revisions_and_export_keep_original_and_all_versions(ctx):
    store = EnterpriseStore(ctx.db)
    store.save_profile(brief())
    result = asyncio.run(generate(ctx, FakeClient()))
    original = copy.deepcopy(store.report(result["report_id"])["output"])
    with pytest.raises(ValueError):
        store.revise(result["report_id"], "修改后的文案", "", True)
    store.revise(result["report_id"], "第一版人工稿", "核实产品信息", True)
    store.revise(result["report_id"], "第二版人工稿", "执行前再次修改，尚未复核", False)
    report = store.report(result["report_id"])
    assert report["output"] == original and len(report["revisions"]) == 2
    exported = export_report(report)
    assert all(v in exported for v in ("第一版人工稿", "第二版人工稿", "待人工复核", "E1", "输入快照", "提示词记录"))
    assert render_output(original) in exported


def test_api_metric_zero_is_not_overridden_by_fallback():
    result = normalize_work({"aweme_id": "1", "statistics": {"play_count": 0, "digg_count": 0}, "play_count": 999, "digg_count": 999})
    assert result["play_count"] == result["digg_count"] == 0
    assert normalize_work({"aweme_id": "2"})["play_count"] is None
