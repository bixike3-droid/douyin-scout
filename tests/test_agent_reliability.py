"""Regression cases at execution, compaction and restart boundaries. No network."""
import asyncio
import json
import time

import pytest

from scout.app import AppContext
from scout.analyze.conversation import send, _maybe_summarize, MAX_TOOL_CALLS, MAX_MODEL_CALLS
from scout.llm import LLMReply, LLMError
from scout.store.chat import ChatRuns
from scout.store.conversation import Conversations
from scout.tools import registry


class SummaryClient:
    def __init__(self):
        self.inputs = []

    async def chat(self, system, body, **kwargs):
        data = json.loads(body)
        self.inputs.append(data)
        return LLMReply(text=data["previous_summary"] + "|" + "|".join(m["content"] for m in data["messages"]), model="summary")


def test_memory_advances_past_window_and_preserves_old_and_uncovered_constraints(ctx):
    store, client = Conversations(ctx.db), SummaryClient()
    cid = store.create("long")
    for index in range(64):
        store.add(cid, "user" if index % 2 == 0 else "assistant", f"constraint-{index}")
        asyncio.run(_maybe_summarize(store, client, cid))
    memory = store.memory(cid)
    assert len(client.inputs) > 4 and memory["covered_message_id"] > 40
    context = memory["summary"] + "|" + "|".join(m["content"] for m in store.context_history(cid))
    assert all(f"constraint-{i}" in context for i in range(64))
    assert client.inputs[-1]["previous_summary"]
    with AppContext.create(ctx.config) as reopened:
        assert Conversations(reopened.db).memory(cid) == memory


def test_failed_compaction_does_not_advance_and_large_messages_are_not_silently_cut(ctx):
    store, client = Conversations(ctx.db), SummaryClient()
    cid = store.create("large")
    for i in range(10):
        store.add(cid, "user" if i % 2 == 0 else "assistant", f"start-{i}" + "x" * 3000 + f"end-{i}")
    class Broken:
        async def chat(self, *args, **kwargs):
            raise LLMError("offline")
    with pytest.raises(LLMError):
        asyncio.run(_maybe_summarize(store, Broken(), cid, force=True))
    assert store.memory(cid) is None
    asyncio.run(_maybe_summarize(store, client, cid, force=True))
    assert all(m["content"].endswith(f"end-{i}") for i, m in enumerate(client.inputs[0]["messages"]))
    store.add(cid, "error", "failed constraint", status="failed")
    assert "failed constraint" not in str(store.context_history(cid))


@pytest.mark.parametrize("args", ["{broken", [], {"count": True}, {"count": "2"}, {}, {"count": 0}, {"count": 4},
                                  {"count": 1, "extra": True}, {"count": 1, "kind": "bad"}])
def test_invalid_arguments_never_reach_confirmation_or_handler(ctx, monkeypatch, args):
    called = []
    async def handler(*unused):
        called.append("handler")
        return {"ok": True}
    async def approve(*unused):
        called.append("confirm")
        return True
    spec = registry.ToolSpec(id="validated", name="test", description="", level="confirm", handler=handler,
                             parameters={"type": "object", "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 3},
                                                                           "kind": {"type": "string", "enum": ["valid"]}},
                                         "required": ["count"], "additionalProperties": False})
    monkeypatch.setitem(registry.REGISTRY, spec.id, spec)
    result = asyncio.run(registry.execute(ctx, spec.id, "steward", args, confirm=approve))
    assert result["code"] == "INVALID_ARGUMENTS" and result["retryable"] and not called
    assert ctx.db.scalar("SELECT status FROM tool_calls ORDER BY id DESC LIMIT 1") == "invalid"


def install_tool(monkeypatch, *, level="read", handler=None):
    async def default(*args):
        return {"ok": True, "summary": "real saved result", "content": "saved evidence"}
    monkeypatch.setitem(registry.REGISTRY, "probe", registry.ToolSpec(
        id="probe", name="测试操作", description="", parameters={"type": "object"}, level=level, handler=handler or default))


def tool_reply(index=1, count=1):
    return LLMReply(text="", model="offline", tool_calls=[{"id": f"call-{index}-{i}", "name": "probe", "arguments": "{}"}
                                                          for i in range(count)], prompt_tokens=10, completion_tokens=5)


def test_batch_tool_budget_saves_partial_when_summary_provider_is_down(ctx, monkeypatch):
    executed = []
    async def handler(*args):
        executed.append(1)
        return {"ok": True, "summary": "done"}
    install_tool(monkeypatch, handler=handler)
    class Loop:
        async def chat_messages(self, *args, **kwargs):
            if kwargs["tools"] is None:
                raise LLMError("summary unavailable")
            return tool_reply(count=MAX_TOOL_CALLS + 2)
    result = asyncio.run(send(ctx, Loop(), "batch", agent_id="steward"))
    run = result["conversation"]["chat_run"]
    assert result["partial"] and not result.get("failed")
    assert len(executed) == MAX_TOOL_CALLS == run["tool_count"]
    assert run["status"] == "partial" and run["model_calls"] <= MAX_MODEL_CALLS
    assert all(c["result"] is not None for c in run["calls"])
    assert all(c["result"]["code"] == "BUDGET_EXHAUSTED" for c in run["calls"][MAX_TOOL_CALLS:])
    assert "done" in result["conversation"]["messages"][-1]["content"]


def test_declined_repeated_call_only_prompts_once_and_survives_reopen(ctx, monkeypatch):
    install_tool(monkeypatch, level="confirm")
    decisions = []
    async def deny(*args):
        decisions.append(1)
        return False
    class Twice:
        calls = 0
        async def chat_messages(self, *args, **kwargs):
            self.calls += 1
            return tool_reply(self.calls) if self.calls <= 2 else LLMReply(text="stopped", model="offline")
    result = asyncio.run(send(ctx, Twice(), "decline", agent_id="steward", confirm=deny))
    assert decisions == [1]
    run = result["conversation"]["chat_run"]
    with AppContext.create(ctx.config) as reopened:
        calls = ChatRuns(reopened.db).get(run["id"])["calls"]
        assert all(c["result"]["code"] == "USER_DECLINED" for c in calls)


def test_completed_tool_result_reused_after_model_failure_and_database_reopen(ctx, monkeypatch):
    executed = []
    async def handler(*args):
        executed.append(1)
        return {"ok": True, "summary": "finished", "content": "durable evidence"}
    install_tool(monkeypatch, handler=handler)
    class Failing:
        calls = 0
        async def chat_messages(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return tool_reply()
            raise LLMError("offline")
    first = asyncio.run(send(ctx, Failing(), "resume", agent_id="steward"))
    assert first["conversation"]["chat_run"]["status"] == "failed"
    class Finish:
        async def chat_messages(self, system, messages, **kwargs):
            assert "durable evidence" in str(messages)
            return LLMReply(text="finished after resume", model="offline", prompt_tokens=20, completion_tokens=7, duration_ms=12)
    with AppContext.create(ctx.config) as reopened:
        result = asyncio.run(send(reopened, Finish(), "continue", conversation_id=1,
                                  chat_run_id=first["conversation"]["chat_run"]["id"]))
    assert executed == [1] and result["conversation"]["chat_run"]["status"] == "complete"
    assistant = result["conversation"]["messages"][-1]
    assert assistant["model"] == "offline" and assistant["prompt_tokens"] == 30 and assistant["completion_tokens"] == 12
    assert ctx.db.scalar("SELECT COUNT(*) FROM model_calls WHERE run_ref='chat:1'") == 3


def test_interrupted_write_is_not_repeated_on_resume(ctx, monkeypatch):
    executed = []
    async def interrupted(*args):
        executed.append(1)
        raise asyncio.CancelledError
    install_tool(monkeypatch, level="confirm", handler=interrupted)
    class Choose:
        async def chat_messages(self, *args, **kwargs):
            return tool_reply()
    async def approve(*args):
        return True
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(send(ctx, Choose(), "write", agent_id="steward", confirm=approve))
    with AppContext.create(ctx.config) as reopened:
        result = asyncio.run(send(reopened, Choose(), "continue", conversation_id=1, chat_run_id=1, confirm=approve))
    assert executed == [1]
    assert result["conversation"]["chat_run"]["status"] == "needs_review"
    assert result["conversation"]["chat_run"]["calls"][0]["result"]["code"] == "NEEDS_REVIEW"


def test_resume_rejects_other_conversation_or_account(ctx, monkeypatch):
    install_tool(monkeypatch)
    class Failed:
        async def chat_messages(self, *args, **kwargs):
            raise LLMError("offline")
    asyncio.run(send(ctx, Failed(), "first", agent_id="steward"))
    cid = Conversations(ctx.db).create("other")
    with pytest.raises(ValueError, match="当前会话"):
        asyncio.run(send(ctx, Failed(), "continue", conversation_id=cid, chat_run_id=1))
    ctx.cursors.set("self_sec_uid", "other")
    with pytest.raises(ValueError, match="账号"):
        asyncio.run(send(ctx, Failed(), "continue", conversation_id=1, chat_run_id=1))


def test_expired_confirmation_is_not_reprompted(ctx, monkeypatch):
    install_tool(monkeypatch, level="confirm")
    store = Conversations(ctx.db)
    cid = store.create("waiting")
    uid = store.add(cid, "user", "waiting", status="pending")
    runs = ChatRuns(ctx.db)
    run = runs.create(cid, uid, "steward", "", "waiting", "system", [{"role": "user", "content": "waiting"}])
    runs.select(run["id"], tool_reply())
    call = runs.get(run["id"])["calls"][0]
    runs.call_state(call["id"], "waiting", expires_at=time.time() - 1)
    called = []
    async def approve(*args):
        called.append(1)
        return True
    result = asyncio.run(registry.execute(ctx, "probe", "steward", {}, conversation_id=cid, confirm=approve, invocation_id=call["id"]))
    assert result["code"] == "USER_DECLINED" and called == []


def test_confirmation_can_be_answered_synchronously_when_card_is_emitted():
    from scout.tools.confirm import ConfirmationBroker
    broker = ConfirmationBroker(timeout_s=.1)
    def emit(event):
        if event["phase"] == "confirm":
            assert broker.resolve(event["request_id"], True)
    callback = broker.confirmer(emit)
    spec = registry.ToolSpec(id="test", name="test", description="", parameters={}, level="confirm")
    assert asyncio.run(callback(spec, "data", {})) is True


def test_delegate_model_calls_share_the_run_budget(ctx, monkeypatch):
    import scout.analyze.conversation as conversation
    monkeypatch.setattr(conversation, "MAX_MODEL_CALLS", 3)
    class DelegateClient:
        actual_calls = 0
        async def chat_messages(self, *args, **kwargs):
            self.actual_calls += 1
            return LLMReply(text="", model="test", tool_calls=[{
                "id": f"delegate-{self.actual_calls}", "name": "delegate",
                "arguments": '{"agent":"content","task":"check evidence"}'}])
        async def chat(self, *args, **kwargs):
            self.actual_calls += 1
            return LLMReply(text="delegated result", model="test")
    client = DelegateClient()
    result = asyncio.run(send(ctx, client, "coordinate", agent_id="steward"))
    assert client.actual_calls == 3 == result["conversation"]["chat_run"]["model_calls"]
    assert result["partial"]
    assert ctx.db.scalar("SELECT COUNT(*) FROM model_calls WHERE purpose='delegate'") == 1


def test_stopped_pending_confirmation_can_resume_after_reopen(ctx, monkeypatch):
    install_tool(monkeypatch, level="confirm")
    selected = asyncio.Event()
    class Client:
        async def chat_messages(self, system, messages, **kwargs):
            if not any(m["role"] == "tool" for m in messages):
                return tool_reply()
            return LLMReply(text="finished", model="offline")
    async def wait_for_decision(*args):
        selected.set()
        await asyncio.Event().wait()
    async def stop():
        task = asyncio.create_task(send(ctx, Client(), "waiting", agent_id="steward", confirm=wait_for_decision))
        await asyncio.wait_for(selected.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(stop())
    run = ChatRuns(ctx.db).get(1)
    assert run["calls"][0]["status"] == "waiting" and run["calls"][0]["approved"] is None
    asked = []
    async def approve(*args):
        asked.append(True)
        return True
    with AppContext.create(ctx.config) as reopened:
        result = asyncio.run(send(reopened, Client(), "continue", conversation_id=1, chat_run_id=1, confirm=approve))
    assert asked == [True] and result["conversation"]["chat_run"]["status"] == "complete"
    assert result["conversation"]["chat_run"]["tool_count"] == 1


def test_upgrade_preserves_existing_conversation_and_legacy_memory(tmp_path):
    import shutil
    from scout.db.connect import Database
    from scout.db.migrate import MIGRATIONS_DIR, migrate
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    for source in MIGRATIONS_DIR.glob("*.sql"):
        if int(source.name.split("_", 1)[0]) <= 20:
            shutil.copy(source, old_migrations / source.name)
    with Database.open(tmp_path / "upgrade.db") as db:
        migrate(db, old_migrations)
        db.execute("INSERT INTO conversations(id,title,created_at,updated_at) VALUES(1,'old','now','now')")
        db.execute("INSERT INTO conversation_messages(conversation_id,role,content,status,created_at) VALUES(1,'user','old constraint','complete','now')")
        db.execute("INSERT INTO conversation_memory(conversation_id,summary,turns,updated_at) VALUES(1,'legacy summary',20,'now')")
        assert migrate(db) == [
            "0021_agent_execution",
            "0022_attachments",
            "0023_attachment_workspace",
            "0024_codex_runtime",
            "0025_agent_workspace",
            "0026_branch_attachment_map",
            "0027_codex_session_tools_digest",
        ]
        assert migrate(db) == []
        store = Conversations(db)
        assert store.memory(1)["covered_message_id"] == 0
        assert store.context_history(1)[0]["content"] == "old constraint"
        assert store.get(1)["chat_run"] is None


def test_out_of_order_summary_cannot_overwrite_newer_progress(ctx):
    store = Conversations(ctx.db)
    cid = store.create("summary order")
    store.save_memory(cid, "newer", 20, 12)
    store.save_memory(cid, "older", 12, 4)
    assert store.memory(cid)["summary"] == "newer" and store.memory(cid)["covered_message_id"] == 12


def test_cancelled_read_can_retry_and_consumes_another_attempt(ctx, monkeypatch):
    executed = []
    async def handler(*args):
        executed.append(True)
        if len(executed) == 1:
            raise asyncio.CancelledError
        return {"ok": True, "summary": "read completed"}
    install_tool(monkeypatch, handler=handler)
    class Client:
        async def chat_messages(self, system, messages, **kwargs):
            return (LLMReply(text="finished", model="test") if any(m["role"] == "tool" for m in messages)
                    else tool_reply())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(send(ctx, Client(), "read", agent_id="steward"))
    result = asyncio.run(send(ctx, Client(), "continue", conversation_id=1, chat_run_id=1))
    assert len(executed) == 2 and result["conversation"]["chat_run"]["tool_count"] == 2
    assert result["conversation"]["chat_run"]["status"] == "complete"


def test_stale_approved_operation_does_not_execute(ctx, monkeypatch):
    install_tool(monkeypatch, level="confirm")
    store = Conversations(ctx.db)
    cid = store.create("approved")
    uid = store.add(cid, "user", "approved", status="pending")
    runs = ChatRuns(ctx.db)
    run = runs.create(cid, uid, "steward", "", "approved", "system", [])
    runs.select(run["id"], tool_reply())
    call = runs.get(run["id"])["calls"][0]
    runs.call_state(call["id"], "approved", approved=True, expires_at=time.time() - 1)
    result = asyncio.run(registry.execute(ctx, "probe", "steward", {}, conversation_id=cid, invocation_id=call["id"]))
    assert result["code"] == "USER_DECLINED"


def test_missing_provider_ids_are_normalized_for_result_pairing(ctx, monkeypatch):
    install_tool(monkeypatch)
    class Client:
        calls = 0
        async def chat_messages(self, system, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMReply(text="", model="test", tool_calls=[{"name": "probe", "arguments": "{}"} for _ in range(2)])
            selected = next(m for m in messages if m.get("tool_calls"))["tool_calls"]
            results = [m for m in messages if m["role"] == "tool"]
            assert [c["id"] for c in selected] == [r["tool_call_id"] for r in results]
            assert len(set(c["id"] for c in selected)) == 2
            return LLMReply(text="done", model="test")
    assert not asyncio.run(send(ctx, Client(), "pairing", agent_id="steward")).get("failed")
