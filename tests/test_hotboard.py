"""热点看板：抓取 + AI 可用性评估的合并与降级路径。"""
import asyncio
import json
from dataclasses import replace as dc_replace

from scout.analyze.hotboard import load_hot_board, profile_digest
from scout.llm import LLMReply


def _word_payload():
    return {"data": {"word_list": [{"word": "乡村振兴", "hot_value": 100},
                                   {"word": "明星绯闻", "hot_value": 90}]}}


def test_profile_digest_handles_empty_and_filled():
    assert profile_digest({}).startswith("（企业资料尚未填写")
    digest = profile_digest({"goal": "吸引散客", "audience": "周边家庭客"})
    assert "传播目标：吸引散客" in digest and "目标客群：周边家庭客" in digest


def test_hot_board_merges_ai_marks(ctx):
    ctx.config = dc_replace(ctx.config, llm=dc_replace(ctx.config.llm, api_key="k"))

    class FakeEval:
        async def chat(self, system, user, **kwargs):
            assert "热点雷达" in system
            return LLMReply(text=json.dumps({"marks": [
                {"i": 1, "mark": "可用", "why": "贴合文旅"},
                {"i": 2, "mark": "无关", "why": "损伤调性"},
            ]}, ensure_ascii=False), model="t")

    async def fetch(context):
        return _word_payload()

    data = asyncio.run(load_hot_board(ctx, client=FakeEval(), fetch=fetch))
    assert data["usable"] == 1 and len(data["topics"]) == 2
    assert data["topics"][0]["mark"] == "可用" and data["topics"][0]["why"] == "贴合文旅"
    assert data["topics"][1]["mark"] == "无关"
    assert data["note"] == ""


def test_hot_board_without_key_skips_evaluation(ctx):
    async def fetch(context):
        return _word_payload()

    data = asyncio.run(load_hot_board(ctx, fetch=fetch))
    assert len(data["topics"]) == 2 and "未配置" in data["note"]
    assert all(topic["mark"] == "" for topic in data["topics"])


def test_hot_board_fetch_failure_is_reported(ctx):
    async def broken(context):
        raise RuntimeError("没登录")

    data = asyncio.run(load_hot_board(ctx, fetch=broken))
    assert "热点获取失败" in data["error"]
    assert "topics" not in data


def test_hot_board_eval_failure_keeps_list(ctx):
    ctx.config = dc_replace(ctx.config, llm=dc_replace(ctx.config.llm, api_key="k"))

    class BrokenEval:
        async def chat(self, *args, **kwargs):
            raise RuntimeError("模型炸了")

    async def fetch(context):
        return _word_payload()

    data = asyncio.run(load_hot_board(ctx, client=BrokenEval(), fetch=fetch))
    assert len(data["topics"]) == 2 and "评估暂不可用" in data["note"]
