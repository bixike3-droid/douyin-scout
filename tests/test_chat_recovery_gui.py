"""Ordinary chat recovery through the desktop's real operation and Qt signals."""
from test_desktop import qt_app, pump
from test_enterprise_gui import settled
from test_workflow_gui import workflow_window
from scout.llm import LLMReply, LLMError
from scout.tools import registry


def test_chat_card_restores_and_resumes_without_repeating_finished_tool(qt_app, ctx, monkeypatch):
    executed = []
    async def handler(*args):
        executed.append(True)
        return {"ok": True, "summary": "已读取测试记录", "content": "durable record"}
    monkeypatch.setitem(registry.REGISTRY, "gui_probe", registry.ToolSpec(
        id="gui_probe", name="测试查询", description="", parameters={}, handler=handler))
    class Client:
        calls = 0
        offline = True
        async def chat(self, *args, **kwargs):
            return LLMReply(text='{"speaker":"steward","workflow":null}', model="route")
        async def chat_messages(self, system, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMReply(text="", model="test", tool_calls=[{"id": "gui-call", "name": "gui_probe", "arguments": "{}"}])
            if self.offline:
                raise LLMError("模拟断网")
            assert "durable record" in str(messages)
            return LLMReply(text="已根据保存的查询结果完成回复。", model="test")
    client = Client()
    window = workflow_window(ctx, monkeypatch, client)
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.composer.setPlainText("查一下已保存的记录")
        pane.generate_button.click()
        card = pane.chat_run_card
        pump(qt_app, lambda: settled(window) and card.run is not None, timeout=10)
        assert card.run["status"] == "failed" and card.resume.isEnabled()
        pane.apply_conversation(window.service.conversation(pane.conversation_id))
        assert card.run["status"] == "failed"
        card.details.click()
        assert card.dialog.isVisible()
        card.dialog.close()
        client.offline = False
        card.resume.click()
        pump(qt_app, lambda: settled(window) and card.run["status"] == "complete", timeout=10)
        assert executed == [True] and not card.resume.isVisible()
        assert pane.conversation_data["messages"][-1]["content"] == "已根据保存的查询结果完成回复。"
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_chat_card_disables_resume_for_uncertain_effect(qt_app):
    from scout.desktop.harness import ChatRunCard
    card = ChatRunCard()
    try:
        card.apply({"id": 1, "agent": "data", "status": "needs_review", "tool_count": 1,
                    "error": "请核对实际结果", "calls": []})
        assert not card.resume.isEnabled() and "核对" in card.title.text()
    finally:
        card.close()
