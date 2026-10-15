import asyncio
import json

import pytest
from test_enterprise import reply_data
from scout.analyze.conversation import send
from scout.llm import LLMReply, LLMError
from scout.store.conversation import Conversations


class ChatClient:
    def __init__(self):
        self.calls = []

    async def chat(self, system, user, **kwargs):
        data = json.loads(user)
        self.calls.append((system, data, kwargs))
        plan = reply_data() if data["want_plan"] else None
        return LLMReply(text=json.dumps({"reply": "这是模型测试回复，已阅读本次消息。", "plan": plan}, ensure_ascii=False), model="chat-test", prompt_tokens=10, completion_tokens=20)


def test_empty_company_fields_allow_real_conversation_and_history(ctx):
    client = ChatClient()
    first = asyncio.run(send(ctx, client, "你好，先聊一下"))
    cid = first["conversation"]["id"]
    assert first["report_id"] is None
    second = asyncio.run(send(ctx, client, "记得我刚才说了什么吗", conversation_id=cid))
    assert len(second["conversation"]["messages"]) == 4
    history = client.calls[-1][2]["history"]
    assert history[0] == {"role": "user", "content": "你好，先聊一下"}
    assert history[1]["role"] == "assistant"
    assert not client.calls[0][1]["context"]["evidence"][0]["data"]["features"]


def test_explicit_plan_is_attached_and_used_as_next_turn_context(ctx):
    client = ChatClient()
    first = asyncio.run(send(ctx, client, "请生成方案", want_plan=True))
    assert first["report_id"] and first["conversation"]["report_id"] == first["report_id"]
    cid = first["conversation"]["id"]
    asyncio.run(send(ctx, client, "请解释第一条", conversation_id=cid))
    evidence = client.calls[-1][1]["context"]["evidence"]
    assert any(e["id"] == "P1" and "周末农耕体验说明" in e["data"] for e in evidence)


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
    class ThinkingClient:
        async def chat(self, system, user, **kwargs):
            on_delta = kwargs.get("on_delta")
            assert kwargs.get("thinking") is True and callable(on_delta)
            on_delta("reasoning", "先核对资料。")
            on_delta("reasoning", "再回答。")
            on_delta("content", '{"reply":')
            return LLMReply(text=json.dumps({"reply": "你好", "plan": None}, ensure_ascii=False),
                            model="thinking-test", reasoning="先核对资料。再回答。")
    events = []
    result = asyncio.run(send(ctx, ThinkingClient(), "打个招呼", emit=events.append))
    assert [e["delta"] for e in events if e.get("type") == "thinking"] == ["先核对资料。", "再回答。"]
    assert any(e.get("type") == "answering" for e in events)
    assistant = result["conversation"]["messages"][-1]
    assert assistant["role"] == "assistant" and assistant["reasoning"] == "先核对资料。再回答。"


def test_forced_agent_replies_and_is_persisted(ctx):
    client = ChatClient()
    result = asyncio.run(send(ctx, client, "谁在点赞？", agent_id="audience"))
    system = client.calls[0][0]
    assert "受众分析师" in system and "本次指定" in system
    messages = result["conversation"]["messages"]
    assert messages[0]["agent"] == "" and messages[-1]["agent"] == "audience"


def test_unknown_forced_agent_falls_back_to_steward(ctx):
    client = ChatClient()
    result = asyncio.run(send(ctx, client, "你好", agent_id="不存在的角色"))
    assert result["conversation"]["messages"][-1]["agent"] == "steward"


def test_team_auto_dispatches_to_the_right_member(ctx):
    class DispatchClient:
        async def chat(self, system, user, **kwargs):
            assert "自动派单" in system and "数据管家" in system and "复盘顾问" in system
            return LLMReply(text=json.dumps({"speaker": "data", "reply": "我去把点赞人取回来。", "plan": None}, ensure_ascii=False),
                            model="dispatch-test")
    result = asyncio.run(send(ctx, DispatchClient(), "把最新的点赞人取回来"))
    messages = result["conversation"]["messages"]
    assert messages[0]["agent"] == "" and messages[-1]["agent"] == "data"


def test_unknown_speaker_falls_back_to_steward(ctx):
    class WeirdClient:
        async def chat(self, system, user, **kwargs):
            return LLMReply(text=json.dumps({"speaker": "ghost", "reply": "你好", "plan": None}, ensure_ascii=False), model="x")
    result = asyncio.run(send(ctx, WeirdClient(), "在吗"))
    assert result["conversation"]["messages"][-1]["agent"] == "steward"


def test_unusable_reply_is_retried_without_thinking(ctx):
    class FlakyClient:
        def __init__(self):
            self.thinking = []

        async def chat(self, system, user, **kwargs):
            self.thinking.append(kwargs.get("thinking"))
            if len(self.thinking) == 1:
                return LLMReply(text="这不是合法JSON，像是被截断的思考产物", model="flaky", reasoning="很长很长的思考……")
            return LLMReply(text=json.dumps({"speaker": "data", "reply": "重试成功。", "plan": None}, ensure_ascii=False), model="flaky")

    client = FlakyClient()
    result = asyncio.run(send(ctx, client, "看看我的数据"))
    assert client.thinking == [True, False]
    assert not result.get("failed")
    messages = result["conversation"]["messages"]
    assert messages[-1]["agent"] == "data" and messages[-1]["content"] == "重试成功。"


def test_reply_still_unusable_after_retry_marks_failure(ctx):
    class BrokenClient:
        async def chat(self, system, user, **kwargs):
            return LLMReply(text="仍然不是JSON", model="broken")

    result = asyncio.run(send(ctx, BrokenClient(), "看看我的数据"))
    assert result.get("failed")
    assert result["conversation"]["messages"][-1]["role"] == "error"
