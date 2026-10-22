"""总管委派与长会话摘要。"""
import asyncio

from scout.llm import LLMReply
from scout.tools import delegate, registry  # noqa: F401 —— 导入即注册


class FakeClient:
    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        return LLMReply(text="结论：建议周五发", model="t")


def test_delegate_returns_member_conclusion(ctx):
    ctx.tool_client = FakeClient()
    ctx.delegate_depth = 0
    ctx.delegate_calls = 0
    result = asyncio.run(registry.execute(ctx, "delegate", "steward",
                                          {"agent": "observer", "task": "看下本周热点"}))
    assert result["ok"] and "结论" in result["content"]
    assert ctx.delegate_calls == 1
    row = ctx.db.query_one("SELECT status FROM tool_calls WHERE tool='delegate'")
    assert row["status"] == "complete"


def test_delegate_guards_permission_depth_and_limit(ctx):
    ctx.tool_client = FakeClient()
    denied = asyncio.run(registry.execute(ctx, "delegate", "data", {"agent": "observer", "task": "x"}))
    assert denied["ok"] is False
    ctx.delegate_depth = 1
    deep = asyncio.run(registry.execute(ctx, "delegate", "steward", {"agent": "observer", "task": "x"}))
    assert deep["ok"] is False and "一层" in deep["summary"]
    ctx.delegate_depth = 0
    ctx.delegate_calls = 3
    limited = asyncio.run(registry.execute(ctx, "delegate", "steward", {"agent": "observer", "task": "x"}))
    assert limited["ok"] is False and "上限" in limited["summary"]


