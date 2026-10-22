"""Verify real handoffs, frozen inputs, scoped collection and durable recovery."""
import asyncio
import copy
import json

import pytest

from scout.analyze.conversation import send
from scout.app import AppContext
from scout.llm import LLMReply, LLMError
from scout.store.conversation import Conversations
from scout.store.enterprise import EnterpriseStore
from scout.store.workflow import Workflows
from test_enterprise import brief, reply_data


class WorkflowClient:
    def __init__(self):
        self.calls = []
        self.fail_stage = None
        self.invalid_stage = None

    async def chat(self, system, user, **kwargs):
        try:
            data = json.loads(user)
        except ValueError:
            return LLMReply(text=json.dumps({"speaker": "strategy", "workflow": "plan"}), model="route-test")
        self.calls.append((system, data, kwargs))
        stage = data["stage"]
        if self.fail_stage == stage:
            raise LLMError("模拟阶段网络中断")
        if stage == "strategy":
            output = reply_data()
            output["topics"] = [dict(output["topics"][0], title=f"选题 {i}") for i in range(1, 4)]
            handoffs = data["handoffs"]
            if handoffs:
                output["strategy"][0]["evidence_ids"] = [handoffs[0]["id"]]
        else:
            output = {"summary": stage + " 阶段分析完成", "findings": [
                {"text": "仅依据当前样本提出待验证结论", "kind": "hypothesis", "evidence_ids": ["A1" if stage == "audience" else "W1"]}],
                "limitations": ["样本规模有限"]}
        if self.invalid_stage == stage:
            output = {"summary": "不合格", "findings": [{"text": "伪造引用", "kind": "observation", "evidence_ids": ["FAKE"]}], "limitations": []}
        return LLMReply(text=json.dumps(output, ensure_ascii=False), model="workflow-test", prompt_tokens=10, completion_tokens=20)


def seed_data(ctx):
    EnterpriseStore(ctx.db).save_profile(brief(account_confirmed=True))
    ctx.cursors.set("self_sec_uid", "owner")
    ctx.works.upsert({"aweme_id": "mine", "author_sec_uid": "owner", "is_mine": 1,
                      "description": "测试作品", "digg_count": 12, "comment_count": 2})
    ctx.users.upsert({"sec_uid": "viewer", "nickname": "测试互动者", "follower_count": 20})
    ctx.like_edges.add_many([{"sec_uid": "viewer", "aweme_id": "mine"}])


def start(ctx, client, **kwargs):
    return asyncio.run(send(ctx, client, "仅用已有数据，分析受众和作品，给我三个下周选题", want_plan=True, **kwargs))


def test_plan_passes_saved_analysis_and_one_snapshot_to_strategy(ctx):
    seed_data(ctx)
    client, events = WorkflowClient(), []
    result = start(ctx, client, emit=events.append)
    assert not result.get("failed")
    run = result["workflow"]
    assert run["status"] == "complete" and len(run["artifacts"]) == 5
    assert [c[1]["stage"] for c in client.calls] == ["audience", "content", "strategy"]
    assert len({c[1]["context"]["snapshot_id"] for c in client.calls}) == 1
    assert client.calls[0][1]["handoffs"] == client.calls[1][1]["handoffs"] == []
    handoffs = client.calls[-1][1]["handoffs"]
    assert [h["data"]["summary"] for h in handoffs] == ["audience 阶段分析完成", "content 阶段分析完成"]
    assert result["report_id"] == result["conversation"]["report_id"]
    assert [m["agent"] for m in result["conversation"]["messages"] if m["role"] == "assistant"] == ["data", "audience", "content", "strategy", "steward"]
    assert any(e.get("type") == "workflow" for e in events)


def test_failed_strategy_resumes_after_reopening_without_reanalyzing_or_refresh(ctx):
    seed_data(ctx)
    client = WorkflowClient()
    client.fail_stage = "strategy"
    first = start(ctx, client)
    run_id = first["workflow"]["id"]
    assert first["failed"] and first["workflow"]["status"] == "failed"
    assert len(first["workflow"]["artifacts"]) == 3
    # A live row changes after failure; resume must retain the old snapshot.
    ctx.db.execute("UPDATE works SET digg_count=999 WHERE aweme_id='mine'")
    client.fail_stage = None
    with AppContext.create(ctx.config) as reopened:
        result = asyncio.run(send(reopened, client, "继续", conversation_id=first["conversation"]["id"], workflow_run_id=run_id))
    assert result["workflow"]["status"] == "complete"
    assert [c[1]["stage"] for c in client.calls] == ["audience", "content", "strategy", "strategy"]
    work = next(e for e in client.calls[-1][1]["context"]["evidence"] if e["id"] == "W1")
    assert work["data"]["digg_count"] == 12
    assert result["workflow"]["steps"][3]["attempts"] == 2


def test_rerun_uses_new_snapshot_and_keeps_previous_artifacts(ctx):
    seed_data(ctx)
    client = WorkflowClient()
    first = start(ctx, client)
    immutable = copy.deepcopy(first["workflow"]["artifacts"])
    ctx.db.execute("UPDATE works SET digg_count=88 WHERE aweme_id='mine'")
    second = asyncio.run(send(ctx, client, "重做", conversation_id=first["conversation"]["id"], workflow_run_id=first["workflow"]["id"], rerun=True))
    assert second["workflow"]["id"] != first["workflow"]["id"]
    assert Workflows(ctx.db).get(first["workflow"]["id"])["artifacts"] == immutable
    assert next(e for e in second["workflow"]["artifacts"][0]["content"]["evidence"] if e["id"] == "W1")["data"]["digg_count"] == 88


def test_cancellation_keeps_completed_steps_and_does_not_run_strategy(ctx):
    seed_data(ctx)

    class Waiting(WorkflowClient):
        async def chat(self, system, user, **kwargs):
            if json.loads(user).get("stage") == "content":
                waiting.set()
                await asyncio.Event().wait()
            return await super().chat(system, user, **kwargs)

    async def exercise():
        nonlocal waiting
        waiting = asyncio.Event()
        task = asyncio.create_task(send(ctx, Waiting(), "仅用已有数据做方案", want_plan=True))
        await asyncio.wait_for(waiting.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    waiting = None
    asyncio.run(exercise())
    run = Workflows(ctx.db).latest(1)
    assert run["status"] == "cancelled"
    assert [a["kind"] for a in run["artifacts"]] == ["data", "audience"]
    assert run["steps"][2]["status"] == "cancelled"
    resumed = asyncio.run(send(ctx, WorkflowClient(), "继续", conversation_id=1, workflow_run_id=run["id"]))
    assert resumed["workflow"]["status"] == "complete"


def test_invalid_analysis_is_retried_once_and_never_handed_to_strategy(ctx):
    seed_data(ctx)
    client = WorkflowClient()
    client.invalid_stage = "audience"
    result = start(ctx, client)
    assert result["failed"] and [c[1]["stage"] for c in client.calls] == ["audience", "audience"]
    assert [a["kind"] for a in result["workflow"]["artifacts"]] == ["data"]
    assert "不存在" in result["workflow"]["error"]
    assert ctx.db.scalar("SELECT COUNT(*) FROM enterprise_reports") == 0


def test_missing_audience_skips_stage_and_marks_partial(ctx):
    seed_data(ctx)
    ctx.db.execute("DELETE FROM like_edges")
    client = WorkflowClient()
    result = start(ctx, client)
    assert result["workflow"]["status"] == "partial"
    assert [c[1]["stage"] for c in client.calls] == ["content", "strategy"]
    assert result["workflow"]["steps"][1]["status"] == "skipped"
    assert "缺少有效互动者" in client.calls[-1][1]["handoffs"][0]["data"]["summary"]


def test_declined_refresh_preserves_old_data_and_never_calls_collection(ctx, monkeypatch):
    seed_data(ctx)
    from scout.desktop import actions
    monkeypatch.setattr(actions, "login_status", lambda paths: {"saved": True})
    called = []

    async def collect(*args):
        called.append(True)
        raise AssertionError("拒绝后不得采集")

    async def deny(spec, agent, args):
        return False

    monkeypatch.setattr(actions, "collect", collect)
    result = asyncio.run(send(ctx, WorkflowClient(), "先更新数据，再生成方案", want_plan=True, confirm=deny))
    assert not called and result["workflow"]["status"] == "partial"
    assert result["workflow"]["artifacts"][0]["content"]["collection"]["ok"] is False
    assert ctx.db.query_one("SELECT status FROM tool_calls ORDER BY id DESC LIMIT 1")[0] == "declined"


def test_structured_partial_collection_reaches_snapshot(ctx, monkeypatch):
    seed_data(ctx)
    from scout.desktop import actions
    monkeypatch.setattr(actions, "login_status", lambda paths: {"saved": True})

    async def collect(*args):
        return {"message": "完成2项，失败1项", "report": {"ok": 2, "failed": 1, "partial": 0}}

    async def approve(*args):
        return True

    monkeypatch.setattr(actions, "collect", collect)
    result = asyncio.run(send(ctx, WorkflowClient(), "更新数据后生成方案", want_plan=True, confirm=approve))
    data = result["workflow"]["artifacts"][0]["content"]
    assert data["collection"]["report"]["failed"] == 1
    assert data["partial"] and result["workflow"]["status"] == "partial"


def test_resume_refuses_other_conversation_or_identity(ctx):
    seed_data(ctx)
    client = WorkflowClient()
    client.fail_stage = "content"
    first = start(ctx, client)
    other = Conversations(ctx.db).create("另一会话")
    with pytest.raises(ValueError, match="不属于"):
        asyncio.run(send(ctx, client, "继续", conversation_id=other, workflow_run_id=first["workflow"]["id"]))
    ctx.cursors.set("self_sec_uid", "another-owner")
    with pytest.raises(ValueError, match="账号"):
        asyncio.run(send(ctx, client, "继续", conversation_id=first["conversation"]["id"], workflow_run_id=first["workflow"]["id"]))


def test_date_scope_excludes_unknown_and_older_works(ctx):
    import time
    seed_data(ctx)
    ctx.works.upsert({"aweme_id": "recent", "is_mine": 1, "create_time": int(time.time())})
    ctx.works.upsert({"aweme_id": "old", "is_mine": 1, "create_time": 1})
    snapshot = Workflows(ctx.db).snapshot(days=7)
    assert [e["data"]["aweme_id"] for e in snapshot["evidence"] if e["id"].startswith("W")] == ["recent"]


def test_plain_question_does_not_escalate_to_workflow(ctx):
    from scout.analyze.workflow import inferred_workflow, needs_live_tools
    assert inferred_workflow("你好") is None
    assert needs_live_tools("你好") is False
    assert ctx.db.scalar("SELECT COUNT(*) FROM workflow_runs") == 0


def test_topic_count_is_checked_before_publishing_report(ctx):
    seed_data(ctx)
    result = asyncio.run(send(ctx, WorkflowClient(), "仅用已有数据，生成两个选题", want_plan=True))
    assert result["failed"] and "2 个选题" in result["workflow"]["error"]
    assert ctx.db.scalar("SELECT COUNT(*) FROM enterprise_reports") == 0


def test_account_execution_lock_is_released_after_exception(ctx):
    from scout.store.workflow import WorkflowLease
    with pytest.raises(RuntimeError):
        with WorkflowLease(ctx.paths.state_dir):
            with pytest.raises(ValueError, match="正在执行"):
                with WorkflowLease(ctx.paths.state_dir):
                    pass
            raise RuntimeError("模拟退出")
    with WorkflowLease(ctx.paths.state_dir):
        pass


def test_collection_checkpoint_prevents_repeat_after_interrupted_data_step(ctx, monkeypatch):
    seed_data(ctx)
    from scout.desktop import actions
    monkeypatch.setattr(actions, "login_status", lambda paths: {"saved": True})
    collected, approvals = [], []

    async def collect(*args):
        collected.append(True)
        return {"message": "已完成采集", "report": {"ok": 1}}

    async def approve(*args):
        approvals.append(True)
        return True

    original = Workflows.snapshot
    reads = []

    def snapshot(self, **kwargs):
        reads.append(True)
        if len(reads) == 2:
            raise asyncio.CancelledError
        return original(self, **kwargs)

    monkeypatch.setattr(actions, "collect", collect)
    monkeypatch.setattr(Workflows, "snapshot", snapshot)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(send(ctx, WorkflowClient(), "更新数据后生成方案", want_plan=True, confirm=approve))
    run = Workflows(ctx.db).latest(1)
    assert run["steps"][0]["checkpoint"]["collection"]["ok"]
    resumed = asyncio.run(send(ctx, WorkflowClient(), "继续", conversation_id=1, workflow_run_id=run["id"], confirm=approve))
    assert resumed["workflow"]["status"] == "complete"
    assert len(collected) == len(approvals) == 1


def test_hot_topic_question_retains_member_search_tools():
    from scout.analyze.workflow import needs_live_tools
    # 实时查询类请求不能升级成固定协作流程，否则会丢掉成员的实时工具
    assert needs_live_tools("联网分析这个热点，请给我三个选题") is True
