"""工具框架：注册表 / 权限 / 审计，以及内置的联网与热点工具。"""
import asyncio
import http.client
import json
import threading
from dataclasses import replace as dc_replace

from scout.config import SearchConfig
from scout.tools import registry
from scout.tools import hot, web


def test_builtin_tools_registered_with_schemas():
    assert {"web_fetch", "web_search", "hot_topics"} <= set(registry.REGISTRY)
    specs = registry.specs_for("steward")
    expected = [spec for spec in registry.REGISTRY.values() if registry.allows(spec, "steward")]
    assert len(specs) == len(expected)
    for spec in specs:
        assert spec["type"] == "function"
        assert spec["function"]["name"] and spec["function"]["description"]
        assert isinstance(spec["function"]["parameters"], dict)
    assert registry.display_name("web_fetch") == "网页读取"


def test_permission_is_enforced_and_audited(ctx):
    async def handler(context, args):
        return {"ok": True, "summary": "跑了"}

    registry.register(registry.ToolSpec(id="secret_tool", name="秘密工具", description="x",
                                        parameters={}, agents=("data",), handler=handler))
    try:
        denied = asyncio.run(registry.execute(ctx, "secret_tool", "audience", {}))
        assert denied["ok"] is False and "权限" in denied["summary"]
        allowed = asyncio.run(registry.execute(ctx, "secret_tool", "data", {"a": 1}))
        assert allowed["ok"] is True and allowed["summary"] == "跑了"
        rows = ctx.db.rows_as_dicts("SELECT agent,tool,status FROM tool_calls ORDER BY id")
        assert rows[-2] == {"agent": "audience", "tool": "secret_tool", "status": "denied"}
        assert rows[-1] == {"agent": "data", "tool": "secret_tool", "status": "complete"}
    finally:
        registry.REGISTRY.pop("secret_tool", None)


def test_handler_failure_becomes_result_and_audit(ctx):
    async def boom(context, args):
        raise RuntimeError("炸了")

    registry.register(registry.ToolSpec(id="boom_tool", name="会炸", description="x",
                                        parameters={}, handler=boom))
    try:
        result = asyncio.run(registry.execute(ctx, "boom_tool", "steward", {}))
        assert result["ok"] is False and "炸了" in result["summary"]
        row = ctx.db.query_one("SELECT status FROM tool_calls WHERE tool='boom_tool'")
        assert row["status"] == "failed"
    finally:
        registry.REGISTRY.pop("boom_tool", None)


def test_web_fetch_extracts_readable_text(ctx, monkeypatch):
    def fake_get(url, timeout=25):
        body = ("<html><head><style>b{}</style></head><body><h1>标题</h1>"
                "<p>正文内容</p><script>var x = 1;</script></body></html>").encode("utf-8")
        return 200, body, "text/html; charset=utf-8"

    monkeypatch.setattr(web, "_http_get", fake_get)
    result = asyncio.run(registry.execute(ctx, "web_fetch", "steward", {"url": "https://example.com/x"}))
    assert result["ok"] is True
    assert "标题" in result["content"] and "正文内容" in result["content"]
    assert "var x" not in result["content"]


def test_web_fetch_rejects_bad_url(ctx):
    result = asyncio.run(registry.execute(ctx, "web_fetch", "steward", {"url": "file:///etc/passwd"}))
    assert result["ok"] is False


def test_web_search_without_key_gives_guidance(ctx):
    result = asyncio.run(registry.execute(ctx, "web_search", "steward", {"query": "热点"}))
    assert result["ok"] is False and "search.provider" in result["summary"]


def test_web_search_tavily_parses_results(ctx, monkeypatch):
    ctx.config = dc_replace(ctx.config, search=SearchConfig(provider="tavily", api_key="k"))

    def fake_post(url, payload, headers, timeout=30):
        assert "tavily" in url and payload["query"] == "热点"
        return {"results": [{"title": "结果标题", "url": "https://a.com", "content": "结果内容"}]}

    monkeypatch.setattr(web, "_http_post_json", fake_post)
    result = asyncio.run(registry.execute(ctx, "web_search", "steward", {"query": "热点", "count": 3}))
    assert result["ok"] is True and "结果标题" in result["content"]


ANTHROPIC_SEARCH_REPLY = {
    "content": [
        {"type": "thinking", "thinking": "先搜索"},
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "热点"}},
        {"type": "web_search_tool_result", "tool_use_id": "t1", "content": [
            {"type": "web_search_result", "title": "来源标题", "url": "https://s.com/a"},
            {"type": "web_search_result", "title": "来源标题二", "url": "https://s.com/b"},
        ]},
        {"type": "text", "text": "这是搜索摘要。"},
    ],
    "usage": {"server_tool_use": {"web_search_requests": 2}},
}


def test_web_search_deepseek_reuses_llm_key(ctx, monkeypatch):
    ctx.config = dc_replace(ctx.config, llm=dc_replace(ctx.config.llm, api_key="k"),
                            search=SearchConfig(provider="deepseek"))

    def fake_post(url, payload, headers, timeout=30):
        assert url == "https://api.deepseek.com/anthropic/v1/messages"
        assert headers["x-api-key"] == "k"
        assert payload["tools"][0]["type"] == "web_search_20260209"
        return ANTHROPIC_SEARCH_REPLY

    monkeypatch.setattr(web, "_http_post_json", fake_post)
    result = asyncio.run(registry.execute(ctx, "web_search", "steward", {"query": "热点", "count": 1}))
    assert result["ok"] is True
    assert "这是搜索摘要" in result["content"]
    assert "来源标题" in result["content"] and "https://s.com/a" in result["content"]
    assert "来源标题二" not in result["content"]      # count=1 时截断
    assert "2 次服务端请求" in result["summary"]


def test_web_search_auto_mode_uses_deepseek_when_key_present(ctx, monkeypatch):
    ctx.config = dc_replace(ctx.config, llm=dc_replace(ctx.config.llm, api_key="k"))

    def fake_post(url, payload, headers, timeout=30):
        return ANTHROPIC_SEARCH_REPLY

    monkeypatch.setattr(web, "_http_post_json", fake_post)
    result = asyncio.run(registry.execute(ctx, "web_search", "steward", {"query": "热点"}))
    assert result["ok"] is True and "来源标题" in result["content"]


def test_web_search_deepseek_retries_transient_read_errors(ctx, monkeypatch):
    ctx.config = dc_replace(ctx.config, llm=dc_replace(ctx.config.llm, api_key="k"))
    calls = {"n": 0}

    def flaky_post(url, payload, headers, timeout=30):
        calls["n"] += 1
        if calls["n"] == 1:                      # 第一次模拟链路掐断
            raise http.client.IncompleteRead(b"partial")
        return ANTHROPIC_SEARCH_REPLY

    monkeypatch.setattr(web, "_http_post_json", flaky_post)
    result = asyncio.run(registry.execute(ctx, "web_search", "steward", {"query": "热点"}))
    assert result["ok"] is True and calls["n"] == 2


def test_web_search_off_disables(ctx):
    ctx.config = dc_replace(ctx.config, search=SearchConfig(provider="off"))
    result = asyncio.run(registry.execute(ctx, "web_search", "steward", {"query": "热点"}))
    assert result["ok"] is False and "关闭" in result["summary"]


def test_hot_topics_parses_word_list(ctx, monkeypatch):
    async def fake_hot(context):
        return {"data": {"word_list": [{"word": "测试热点一", "hot_value": 123}, {"word": "测试热点二"}]}}

    monkeypatch.setattr(hot, "_douyin_hot", fake_hot)
    result = asyncio.run(registry.execute(ctx, "hot_topics", "strategy", {"limit": 2}))
    assert result["ok"] is True
    assert "1. 测试热点一" in result["content"] and "热度 123" in result["content"]


def test_hot_topics_tolerates_missing_structure():
    assert hot._extract_words({}) == []
    assert hot._extract_words({"data": {"list": [{"sentence": "句子"}]}}) == [{"sentence": "句子"}]


def test_hot_topics_owned_by_observer_and_strategy():
    spec = registry.get("hot_topics")
    assert spec.agents == ("observer", "strategy")
    assert registry.allows(spec, "observer") and registry.allows(spec, "strategy")
    assert not registry.allows(spec, "steward")


def test_unknown_tool_rejected(ctx):
    result = asyncio.run(registry.execute(ctx, "not_a_tool", "steward", {}))
    assert result["ok"] is False


def test_confirm_level_tool_requires_channel(ctx):
    async def handler(context, args):
        return {"ok": True, "summary": "执行了"}

    registry.register(registry.ToolSpec(id="risky_tool", name="风险工具", description="x",
                                        parameters={}, level="confirm", handler=handler))
    try:
        result = asyncio.run(registry.execute(ctx, "risky_tool", "steward", {}))
        assert result["ok"] is False and "确认" in result["summary"]
        row = ctx.db.query_one("SELECT status FROM tool_calls WHERE tool='risky_tool'")
        assert row["status"] == "denied"
    finally:
        registry.REGISTRY.pop("risky_tool", None)


def test_confirm_level_tool_executes_only_after_approval(ctx):
    ran = []

    async def handler(context, args):
        ran.append(1)
        return {"ok": True, "summary": "执行了"}

    async def approve(spec, agent_id, args):
        return True

    async def decline(spec, agent_id, args):
        return False

    registry.register(registry.ToolSpec(id="risky_tool", name="风险工具", description="x",
                                        parameters={}, level="confirm", handler=handler))
    try:
        denied = asyncio.run(registry.execute(ctx, "risky_tool", "steward", {}, confirm=decline))
        assert denied["ok"] is False and ran == []
        allowed = asyncio.run(registry.execute(ctx, "risky_tool", "steward", {}, confirm=approve))
        assert allowed["ok"] is True and ran == [1]
        rows = ctx.db.rows_as_dicts("SELECT status FROM tool_calls WHERE tool='risky_tool' ORDER BY id")
        assert [row["status"] for row in rows] == ["declined", "complete"]
    finally:
        registry.REGISTRY.pop("risky_tool", None)


def test_confirmation_broker_round_trip_across_threads():
    from scout.tools.confirm import ConfirmationBroker

    broker = ConfirmationBroker(timeout_s=5)
    rid = broker.new_id()
    box = {}

    def from_ui_thread():
        # 模拟 Qt 主线程：在另一个线程里把用户选择送回来
        for _ in range(200):
            if broker.resolve(rid, True):
                box["ok"] = True
                return
            import time as _time
            _time.sleep(0.005)

    async def main():
        task = asyncio.create_task(broker.ask(rid))
        thread = threading.Thread(target=from_ui_thread)
        thread.start()
        approved = await task
        thread.join()
        return approved

    assert asyncio.run(main()) is True and box.get("ok") is True


def test_confirmation_broker_confirmer_emits_events():
    from scout.tools.confirm import ConfirmationBroker

    broker = ConfirmationBroker(timeout_s=5)
    events = []
    ask_user = broker.confirmer(events.append)
    spec = registry.ToolSpec(id="cleanup", name="清理", description="", parameters={}, level="confirm")

    async def main():
        async def ui():
            for _ in range(200):
                pending = [e for e in events if e.get("phase") == "confirm"]
                if pending:
                    broker.resolve(pending[0]["request_id"], False)
                    return
                await asyncio.sleep(0.005)
        ui_task = asyncio.create_task(ui())
        approved = await ask_user(spec, "data", {"scope": "all"})
        await ui_task
        return approved

    assert asyncio.run(main()) is False
    assert [e.get("phase") for e in events] == ["confirm", "confirm_done"]
    assert events[0]["tool"] == "cleanup" and events[0]["agent"] == "data"
    assert events[-1]["approved"] is False


def test_data_overview_reports_counts(ctx):
    result = asyncio.run(registry.execute(ctx, "data_overview", "data", {}))
    assert result["ok"] is True
    assert "作品" in result["content"] and "互动者" in result["content"]


def test_records_search_empty_and_bad_view(ctx):
    empty = asyncio.run(registry.execute(ctx, "records_search", "data", {"view": "users", "query": "不存在"}))
    assert empty["ok"] is True and "没有" in empty["summary"]
    bad = asyncio.run(registry.execute(ctx, "records_search", "data", {"view": "nope"}))
    assert bad["ok"] is False


def test_collect_tools_are_data_only_and_confirm_level():
    login = registry.get("collect_login")
    start = registry.get("collect_start")
    assert login is not None and start is not None
    assert login.level == "confirm" and start.level == "confirm"
    assert login.agents == ("data",) and start.agents == ("data",)
    assert registry.allows(start, "data") and not registry.allows(start, "audience")
    names = {item["function"]["name"] for item in registry.specs_for("audience")}
    assert "collect_start" not in names


def test_collect_start_runs_action_after_approval(ctx, monkeypatch):
    from scout.desktop import actions

    captured = {}

    async def fake_collect(context, emit, options):
        captured["options"] = options
        emit({"message": "第 1 个任务 · 点赞人名单：成功"})
        return {"message": "采集结束：完成 2 项（采样 2）；有效互动者 3 人。"}

    monkeypatch.setattr(actions, "collect", fake_collect)
    events = []
    ctx.tool_emit = events.append

    async def approve(spec, agent_id, args):
        return True

    result = asyncio.run(registry.execute(ctx, "collect_start", "data",
                                          {"kinds": "quick", "limit": 20}, confirm=approve))
    assert result["ok"] is True and "采集结束" in result["summary"]
    assert captured["options"] == {"kinds": "quick", "limit": 20, "force": False}
    assert events and events[0]["message"].startswith("第 1 个任务")
    row = ctx.db.query_one("SELECT status FROM tool_calls ORDER BY id DESC LIMIT 1")
    assert row["status"] == "complete"


def test_collect_start_declined_never_runs(ctx, monkeypatch):
    from scout.desktop import actions

    called = []

    async def fake_collect(context, emit, options):
        called.append(1)
        return {"message": "不该被调用"}

    monkeypatch.setattr(actions, "collect", fake_collect)

    async def decline(spec, agent_id, args):
        return False

    result = asyncio.run(registry.execute(ctx, "collect_start", "data", {}, confirm=decline))
    assert result["ok"] is False and called == []
    row = ctx.db.query_one("SELECT status FROM tool_calls ORDER BY id DESC LIMIT 1")
    assert row["status"] == "declined"


def test_collect_start_reports_action_errors(ctx, monkeypatch):
    from scout.desktop import actions

    async def fake_collect(context, emit, options):
        raise ValueError("请先点击窗口顶部的「登录抖音」")

    monkeypatch.setattr(actions, "collect", fake_collect)

    async def approve(spec, agent_id, args):
        return True

    result = asyncio.run(registry.execute(ctx, "collect_start", "data", {}, confirm=approve))
    assert result["ok"] is False and "登录抖音" in result["summary"]
