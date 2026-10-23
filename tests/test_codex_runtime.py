"""Protocol, permission and restart boundaries; no network or real credentials."""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import signal
import subprocess
import time

import pytest

from scout.codex.runtime import AppServer, CodexError, prepare_runtime
from scout.config import LLMConfig
from scout.llm import LLMReply
from scout.llm.tracked import TrackedClient
from scout.store.chat import ChatRuns
from scout.store.conversation import Conversations
from scout.tools import registry
from scout.analyze import codex_conversation as adapter


def test_runtime_isolates_home_and_credentials(paths, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "personal-home")
    monkeypatch.setenv("OPENAI_API_KEY", "personal-secret")
    cfg = LLMConfig(api_key="trial-secret", model="deepseek-flash")
    home, work, env = prepare_runtime(paths, cfg)
    assert env["CODEX_HOME"] == str(home) and work.is_relative_to(paths.state_dir)
    assert env["DEEPSEEK_API_KEY"] == "trial-secret" and "OPENAI_API_KEY" not in env
    assert os.environ["CODEX_HOME"] == "personal-home"
    config = (home / "config.toml").read_text(encoding="utf-8")
    assert "trial-secret" not in config and 'wire_api = "responses"' in config
    catalog = json.loads((home / "models.json").read_text(encoding="utf-8"))
    assert "image" in catalog["models"][0]["input_modalities"]
    with pytest.raises(CodexError):
        prepare_runtime(paths, replace(cfg, model="wrong-model"))


def test_transport_handles_large_unicode_frames_interleaving_and_exit():
    program = '''
import sys,json
for line in sys.stdin.buffer:
    msg=json.loads(line)
    if "id" not in msg: continue
    if msg["method"]=="die": sys.exit(2)
    print(json.dumps({"method":"progress","params":{"state":"running"}}),flush=True)
    result={"text":"\\u753b"*100000} if msg["method"]=="big" else {}
    print(json.dumps({"id":msg["id"],"result":result}),flush=True)
'''
    async def run():
        async with AppServer([sys.executable, "-u", "-c", program]) as rpc:
            result = await rpc.request("big", {})
            assert result["text"] == "画" * 100000
            assert (await rpc.events.get())["method"] == "progress"
            with pytest.raises(CodexError, match="关闭"):
                await rpc.request("die", {})
    asyncio.run(run())


def test_close_finishes_when_a_helper_inherits_the_servers_output_pipes():
    program = """
import subprocess,sys,time
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],stdout=sys.stdout,stderr=sys.stderr)
print(child.pid,flush=True)
time.sleep(30)
"""
    async def run():
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        rpc = AppServer([])
        rpc.process = await asyncio.create_subprocess_exec(sys.executable, "-u", "-c", program,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options)
        helper = int(await rpc.process.stdout.readline())
        started = time.monotonic()
        try:
            await asyncio.wait_for(rpc.close(), 9)
            assert time.monotonic() - started < 8
        finally:
            try:
                os.kill(helper, signal.SIGTERM)
            except ProcessLookupError:
                pass
    asyncio.run(run())


def make_run(ctx):
    store = Conversations(ctx.db)
    cid = store.create("probe")
    uid = store.add(cid, "user", "request", status="pending")
    run = ChatRuns(ctx.db).create(cid, uid, "steward", "", "request", "system", [])
    ctx.db.execute("INSERT INTO codex_runs(run_id,model,provider_url) VALUES(?,?,?)", (run["id"], "deepseek-flash", "https://api.deepseek.com"))
    return run


def test_tool_replay_uses_saved_result_and_rejects_changed_arguments(ctx, monkeypatch):
    called = []
    async def handler(ctx, args):
        called.append(args)
        return {"ok": True, "summary": "saved"}
    monkeypatch.setitem(registry.REGISTRY, "probe", registry.ToolSpec("probe", "Probe", "", {"type": "object"}, handler=handler))
    run = make_run(ctx)
    async def perform():
        result = await adapter._tool(ctx, run["id"], "call1", "probe", {"x": 1}, lambda e: None, None)
        assert await adapter._tool(ctx, run["id"], "call1", "probe", {"x": 1}, lambda e: None, None) == result
        with pytest.raises(CodexError, match="改变"):
            await adapter._tool(ctx, run["id"], "call1", "probe", {"x": 2}, lambda e: None, None)
    asyncio.run(perform())
    assert called == [{"x": 1}]


def test_confirmation_and_validation_cannot_be_bypassed_by_engine(ctx, monkeypatch):
    called, approvals = [], []
    async def handler(ctx, args):
        called.append(args)
        return {"ok": True}
    async def decline(*args):
        approvals.append(1)
        return False
    monkeypatch.setitem(registry.REGISTRY, "sensitive", registry.ToolSpec("sensitive", "Sensitive", "",
        {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}, level="confirm", handler=handler))
    run = make_run(ctx)
    async def perform():
        invalid = await adapter._tool(ctx, run["id"], "invalid", "sensitive", {"n": "bad"}, lambda e: None, decline)
        assert invalid["code"] == "INVALID_ARGUMENTS" and not approvals
        for call_id, args in (("decline", {"n": 1, "label": "x"}), ("same-action-new-id", {"label": "x", "n": 1})):
            result = await adapter._tool(ctx, run["id"], call_id, "sensitive", args, lambda e: None, decline)
            assert result["code"] == "USER_DECLINED"
    asyncio.run(perform())
    assert not called and approvals == [1]


def test_interrupted_mutation_is_not_repeated(ctx, monkeypatch):
    called = []
    async def handler(ctx, args):
        called.append(1)
        return {"ok": True}
    monkeypatch.setitem(registry.REGISTRY, "write", registry.ToolSpec("write", "Write", "", {"type": "object"}, level="confirm", handler=handler))
    run = make_run(ctx)
    runs = ChatRuns(ctx.db)
    runs.select(run["id"], LLMReply("", "test", tool_calls=[{"id": "before-crash", "name": "write", "arguments": "{}"}]))
    runs.call_state(runs.get(run["id"])["calls"][0]["id"], "running", approved=True)
    result = asyncio.run(adapter._tool(ctx, run["id"], "before-crash", "write", {}, lambda e: None, None))
    assert result["code"] == "NEEDS_REVIEW" and not called


class ScriptedServer:
    def __init__(self, events=(), recovered=None):
        self.events = asyncio.Queue()
        for event in events:
            self.events.put_nowait(event)
        self.requests, self.responses, self.recovered = [], [], recovered
    async def __aenter__(self): return self
    async def __aexit__(self, *unused): pass
    def clean(self, value): return str(value)
    async def respond(self, key, result): self.responses.append((key, result))
    async def write(self, message): self.responses.append(message)
    async def request(self, method, params, **kwargs):
        self.requests.append((method, params))
        if method == "thread/turns/list":
            return {"data": [self.recovered] if self.recovered else [], "nextCursor": None}
        if method.startswith("thread/"):
            return {"thread": {"id": "thread1"}}
        return {"turn": {"id": "turn1"}}


def test_completed_turn_recovered_without_resubmitting_or_reexecuting(ctx, monkeypatch):
    run = make_run(ctx)
    adapter._update(ctx, run["id"], input_sent=1, thread_id="thread1", turn_id="turn1")
    fake = ScriptedServer(recovered={"id": "turn1", "status": "completed", "items": [
        {"id": "answer1", "type": "agentMessage", "phase": "final_answer", "text": "saved answer"}]})
    monkeypatch.setattr(adapter, "server", lambda *args: fake)
    client = TrackedClient(object(), ctx.db, run["conversation_id"])
    result = asyncio.run(adapter.run_codex(ctx, client, run, lambda e: None))
    assert result["conversation"]["messages"][-1]["content"] == "saved answer"
    assert all(method != "turn/start" for method, args in fake.requests)


def test_failed_turn_never_becomes_success_and_secret_is_redacted(ctx, monkeypatch):
    ctx.config = replace(ctx.config, llm=LLMConfig(api_key="hidden-test-key", model="deepseek-flash"))
    run = make_run(ctx)
    fake = ScriptedServer(events=[{"method": "turn/completed", "params": {"threadId": "thread1", "turn": {
        "id": "turn1", "status": "failed", "error": {"message": "401 hidden-test-key"}}}}])
    monkeypatch.setattr(adapter, "server", lambda *args: fake)
    result = asyncio.run(adapter.run_codex(ctx, TrackedClient(object(), ctx.db, run["conversation_id"]), run, lambda e: None))
    assert result["failed"] and result["conversation"]["chat_run"]["status"] == "failed"
    assert "hidden-test-key" not in json.dumps(result)


def test_cancelled_run_is_durable_and_connection_exits(ctx, monkeypatch):
    run = make_run(ctx)
    fake = ScriptedServer()
    monkeypatch.setattr(adapter, "server", lambda *args: fake)
    async def perform():
        task = asyncio.create_task(adapter.run_codex(ctx, TrackedClient(object(), ctx.db, run["conversation_id"]), run, lambda e: None))
        while not any(method == "turn/start" for method, args in fake.requests):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(perform())
    saved = ChatRuns(ctx.db).get(run["id"])
    assert saved["status"] == "cancelled"
    assert adapter._meta(ctx, run["id"])["turn_id"] == "turn1"
    assert Conversations(ctx.db).get(run["conversation_id"])["messages"][-1]["status"] == "cancelled"
