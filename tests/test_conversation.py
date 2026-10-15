import asyncio
import json

import pytest
from test_enterprise import reply_data
from scout.analyze.conversation import send
from scout.llm import LLMReply, LLMError
from scout.store.conversation import Conversations


class ChatClient:
    """计划路径的假客户端：一次 JSON 调用返回 reply(+plan)。"""

    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        data = json.loads(user)
        self.calls.append((system, data, kwargs))
        plan = reply_data() if data["want_plan"] else None
        return LLMReply(text=json.dumps({"reply": "这是模型测试回复，已阅读本次消息。", "plan": plan}, ensure_ascii=False), model="chat-test", prompt_tokens=10, completion_tokens=20)


class TeamClient:
    """普通对话的假客户端：派单走 chat（小调用），回复走 chat_messages。"""

    def __init__(self, speaker="steward", reply="好的。", reasoning=""):
        self.speaker = speaker
        self.reply = reply
        self.reasoning = reasoning
        self.route_calls = []
        self.message_calls = []

    async def chat(self, system, user, **kwargs):
        self.route_calls.append((system, user, kwargs))
        return LLMReply(text=json.dumps({"speaker": self.speaker}, ensure_ascii=False), model="route-test")

    async def chat_messages(self, system, messages, **kwargs):
        self.message_calls.append((system, messages, kwargs))
        return LLMReply(text=self.reply, model="member-test", reasoning=self.reasoning)


def test_chat_dispatches_to_member_and_persists(ctx):
    client = TeamClient(speaker="audience", reply="先看看点赞的都是谁。")
    result = asyncio.run(send(ctx, client, "谁在点赞？"))
    assert "调度器" in client.route_calls[0][0]
    system = client.message_calls[0][0]
    assert "受众分析师" in system
    messages = result["conversation"]["messages"]
    assert messages[0]["agent"] == "" and messages[-1]["agent"] == "audience"
    assert messages[-1]["content"] == "先看看点赞的都是谁。"
    # 续聊：第二轮的成员调用里应带上此前对话
    conversation_id = result["conversation"]["id"]
    asyncio.run(send(ctx, client, "再具体点", conversation_id=conversation_id))
    sent = client.message_calls[-1][1]
    assert any(m.get("content") == "先看看点赞的都是谁。" for m in sent)


def test_explicit_plan_is_attached_and_used_as_next_turn_context(ctx):
    client = ChatClient()
    first = asyncio.run(send(ctx, client, "请生成方案", want_plan=True))
    assert first["report_id"] and first["conversation"]["report_id"] == first["report_id"]
    follow = TeamClient(reply="第一条的意思是……")
    asyncio.run(send(ctx, follow, "请解释第一条", conversation_id=first["conversation"]["id"]))
    system = follow.message_calls[-1][0]
    assert "周末农耕体验说明" in system


def test_provider_failure_is_persisted_without_fake_assistant_or_plan(ctx):
    class Failed:
        async def chat(self, *args, **kwargs):
            raise LLMError("test HTTP 401")
    result = asyncio.run(send(ctx, Failed(), "你好"))
    assert result["failed"] and result["report_id"] is None
    messages = result["conversation"]["messages"]
    assert messages[0]["status"] == "failed" and messages[-1]["role"] == "error"
    assert not any(m["role"] == "assistant" for m in messages)
    assert not Conversations(ctx.db).history(result["conversation"]["id"])


def test_cancelled_turn_is_not_successful_or_added_to_model_history(ctx):
    class Waiting:
        async def chat(self, *args, **kwargs):
            await asyncio.sleep(60)
    async def exercise():
        task = asyncio.create_task(send(ctx, Waiting(), "待取消消息"))
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(exercise())
    conversation = Conversations(ctx.db).get(1)
    assert all(m["status"] == "cancelled" for m in conversation["messages"])
    assert not Conversations(ctx.db).history(1)


def test_invalid_plan_preserves_reply_and_does_not_create_report(ctx):
    class Invalid:
        async def chat(self, *args, **kwargs):
            return LLMReply(text=json.dumps({"reply": "可阅读的模型回复", "plan": {"bad": True}}), model="test")
    result = asyncio.run(send(ctx, Invalid(), "请生成方案", want_plan=True))
    assert "可阅读的模型回复" in result["conversation"]["messages"][-1]["content"]
    assert result["report_id"] is None and ctx.db.scalar("SELECT COUNT(*) FROM enterprise_reports") == 0


def test_thinking_deltas_reach_the_ui_and_reasoning_is_persisted(ctx):
    class ThinkingTeam(TeamClient):
        async def chat_messages(self, system, messages, **kwargs):
            on_delta = kwargs.get("on_delta")
            assert kwargs.get("thinking") is True and callable(on_delta)
            on_delta("reasoning", "先核对资料。")
            on_delta("reasoning", "再回答。")
            on_delta("content", "你好。")
            return LLMReply(text="你好。", model="thinking-test", reasoning="先核对资料。再回答。")

    events = []
    result = asyncio.run(send(ctx, ThinkingTeam(), "打个招呼", emit=events.append))
    assert [e["delta"] for e in events if e.get("type") == "thinking"] == ["先核对资料。", "再回答。"]
    assert any(e.get("type") == "answering" for e in events)
    assert any(e.get("type") == "assigned" for e in events)
    assistant = result["conversation"]["messages"][-1]
    assert assistant["role"] == "assistant" and assistant["reasoning"] == "先核对资料。再回答。"
    assert assistant["agent"] == "steward"


def test_forced_agent_replies_and_is_persisted(ctx):
    client = TeamClient(reply="我看点赞人。")
    result = asyncio.run(send(ctx, client, "谁在点赞？", agent_id="audience"))
    assert client.route_calls == []  # 指定发言人时不走派单
    system = client.message_calls[0][0]
    assert "受众分析师" in system
    messages = result["conversation"]["messages"]
    assert messages[0]["agent"] == "" and messages[-1]["agent"] == "audience"


def test_unknown_forced_agent_falls_back_to_steward(ctx):
    result = asyncio.run(send(ctx, TeamClient(), "你好", agent_id="不存在的角色"))
    assert result["conversation"]["messages"][-1]["agent"] == "steward"


def test_team_auto_dispatches_to_the_right_member(ctx):
    client = TeamClient(speaker="data", reply="我去把点赞人取回来。")
    result = asyncio.run(send(ctx, client, "把最新的点赞人取回来"))
    assert "数据管家" in client.route_calls[0][0]  # 名册提供给了调度器
    messages = result["conversation"]["messages"]
    assert messages[0]["agent"] == "" and messages[-1]["agent"] == "data"
    assert messages[-1]["content"] == "我去把点赞人取回来。"


def test_unknown_speaker_falls_back_to_steward(ctx):
    result = asyncio.run(send(ctx, TeamClient(speaker="ghost"), "在吗"))
    assert result["conversation"]["messages"][-1]["agent"] == "steward"


def test_empty_member_reply_is_retried_without_thinking(ctx):
    class FlakyTeam(TeamClient):
        async def chat_messages(self, system, messages, **kwargs):
            self.message_calls.append((system, messages, kwargs))
            if kwargs.get("thinking"):
                return LLMReply(text="", model="flaky", reasoning="很长很长的思考……")
            return LLMReply(text="重试成功。", model="flaky")

    client = FlakyTeam()
    result = asyncio.run(send(ctx, client, "看看我的数据"))
    assert [kwargs.get("thinking") for _, _, kwargs in client.message_calls] == [True, False]
    assert not result.get("failed")
    assert result["conversation"]["messages"][-1]["content"] == "重试成功。"


def test_reply_still_unusable_after_retry_marks_failure(ctx):
    class BrokenClient:
        async def chat(self, system, user, **kwargs):
            return LLMReply(text="仍然不是JSON", model="broken")

    result = asyncio.run(send(ctx, BrokenClient(), "看看我的数据"))
    assert result.get("failed")
    assert result["conversation"]["messages"][-1]["role"] == "error"


def test_member_uses_tool_and_feeds_result_back(ctx, monkeypatch):
    from scout.tools import registry as tools

    async def fake_fetch(context, args):
        return {"ok": True, "summary": "已读取网页（123 字）", "content": "正文内容"}

    monkeypatch.setitem(tools.REGISTRY, "web_fetch",
                        tools.ToolSpec(id="web_fetch", name="网页读取", description="测试用", parameters={},
                                       handler=fake_fetch))

    class ToolTeam(TeamClient):
        async def chat_messages(self, system, messages, **kwargs):
            self.message_calls.append((system, messages, kwargs))
            if len(self.message_calls) == 1:
                return LLMReply(text="", model="m",
                                tool_calls=[{"id": "call_1", "name": "web_fetch",
                                             "arguments": json.dumps({"url": "https://example.com"})}])
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            assert tool_messages and "已读取网页" in tool_messages[-1]["content"]
            return LLMReply(text="网页我看过了，内容如下……", model="m")

    events = []
    result = asyncio.run(send(ctx, ToolTeam(), "帮我看看这个网页", emit=events.append))
    kinds = [(e.get("type"), e.get("phase")) for e in events if e.get("type") == "tool"]
    assert kinds == [("tool", "start"), ("tool", "done")]
    assert result["conversation"]["messages"][-1]["content"].startswith("网页我看过了")
    row = ctx.db.query_one("SELECT agent,tool,status FROM tool_calls ORDER BY id DESC LIMIT 1")
    assert row["agent"] == "steward" and row["tool"] == "web_fetch" and row["status"] == "complete"


def test_confirm_tool_denied_by_user_is_reported_back(ctx, monkeypatch):
    from scout.tools import registry as tools

    ran = []

    async def cleanup(context, args):
        ran.append(1)
        return {"ok": True, "summary": "清理完成"}

    monkeypatch.setitem(tools.REGISTRY, "cleanup_tool",
                        tools.ToolSpec(id="cleanup_tool", name="清理缓存", description="测试用", parameters={},
                                       level="confirm", handler=cleanup))

    class ToolTeam(TeamClient):
        async def chat_messages(self, system, messages, **kwargs):
            self.message_calls.append((system, messages, kwargs))
            if len(self.message_calls) == 1:
                return LLMReply(text="", model="m",
                                tool_calls=[{"id": "call_1", "name": "cleanup_tool", "arguments": "{}"}])
            tool_messages = [m for m in messages if m.get("role") == "tool"]
            assert tool_messages and "没有允许" in tool_messages[-1]["content"]
            return LLMReply(text="明白，先不清理。", model="m")

    asked = []

    async def deny(spec, agent_id, args):
        asked.append(spec.id)
        return False

    result = asyncio.run(send(ctx, ToolTeam(), "帮我清理一下", confirm=deny))
    assert asked == ["cleanup_tool"] and ran == []
    assert result["conversation"]["messages"][-1]["content"].startswith("明白")
    row = ctx.db.query_one("SELECT status FROM tool_calls ORDER BY id DESC LIMIT 1")
    assert row["status"] == "declined"
