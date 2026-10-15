"""Native harness task input, truthful progress, history and reduced motion."""
import asyncio

from test_desktop import qt_app, pump
from test_enterprise import brief, FakeClient
from test_enterprise_gui import settled
from scout.desktop.service import DesktopService
from scout.store.enterprise import EnterpriseStore
from scout.analyze.enterprise import generate


def test_composer_enter_creates_real_task_and_new_draft_stays_empty(qt_app, ctx, monkeypatch):
    import scout.llm
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from scout.desktop.window import MainWindow
    store = EnterpriseStore(ctx.db)
    store.save_profile(brief())
    service = DesktopService(ctx.paths)
    service.save_settings("sk-test-never-sent", "test-model")
    client = FakeClient()
    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: client)
    window = MainWindow(service)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.composer.setPlainText("测试需求：针对周末散客提出两种内容表达")
        QTest.keyClick(pane.composer, Qt.Key.Key_Return)
        pump(qt_app, lambda: pane.current_report is not None and settled(window))
        assert client.calls[0][1]["evidence"][0]["data"]["request"] == "测试需求：针对周末散客提出两种内容表达"
        assert window.recent_tasks.count() == 1
        assert pane.plan_layout.count() > 4
        report_id = pane.current_report["id"]
        window.new_task_button.click()
        pump(qt_app, lambda: settled(window))
        assert pane.current_report is None and pane.new_task_mode
        assert not pane.editor.toPlainText()
        pane.generate_button.click()
        pump(qt_app, lambda: settled(window))
        assert len(client.calls) == 1  # an empty new task must not incur a call
        window.refresh()
        pump(qt_app, lambda: settled(window))
        assert pane.current_report is None
        window.recent_tasks.setCurrentRow(0)
        pump(qt_app, lambda: pane.current_report is not None and settled(window))
        assert pane.current_report["id"] == report_id
    finally:
        window.close()


def test_real_processing_events_and_cache_skip_model_stage(ctx):
    EnterpriseStore(ctx.db).save_profile(brief())
    client, events = FakeClient(), []
    asyncio.run(generate(ctx, client, emit=events.append))
    assert [e["phase"] for e in events] == [0, 1, 2, 3]
    assert "暂无已关联作品" in events[1]["message"]
    events.clear()
    asyncio.run(generate(ctx, client, emit=events.append))
    assert [e["phase"] for e in events] == [0, 1, 3] and len(client.calls) == 1


def test_motion_can_be_disabled_and_preference_survives_restart(qt_app, ctx):
    from PySide6.QtCore import QAbstractAnimation
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        window.enterprise.activity.set_running(True)
        assert window.enterprise.activity.animation.state() == QAbstractAnimation.State.Running
        window.motion_toggle.setChecked(False)
        assert window.enterprise.activity.animation.state() == QAbstractAnimation.State.Stopped
        stage = window.enterprise.stage_cards[0]
        stage.set_expanded(False)
        assert stage.animation.state() == QAbstractAnimation.State.Stopped
        assert not stage.body.isVisible()
        window.enterprise.activity.set_running(False)
    finally:
        window.close()
    restarted = MainWindow(DesktopService(ctx.paths))
    restarted.show()
    try:
        pump(qt_app, lambda: restarted.initialized and settled(restarted))
        assert not restarted.motion_enabled and not restarted.motion_toggle.isChecked()
    finally:
        restarted.close()


def test_forms_and_custom_window_controls_close_with_application(qt_app, ctx):
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    pump(qt_app, lambda: window.initialized and settled(window))
    window.enterprise.open_forms(0)
    assert window.enterprise.forms_dialog.isVisible()
    window.title_bar.toggle_maximized()
    assert window.isMaximized()
    window.title_bar.toggle_maximized()
    assert not window.isMaximized()
    window.close()
    assert not window.isVisible() and not window.enterprise.forms_dialog.isVisible()


def test_team_bar_lists_members_without_manual_picking(qt_app):
    from PySide6.QtWidgets import QLabel, QPushButton
    from scout.analyze.agents import TEAM
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        labels = [label.text() for label in pane.agent_bar.findChildren(QLabel)]
        for member in TEAM:
            assert member.name in labels
        # 派单由团队自动完成：界面上没有“选人”控件。
        assert not pane.agent_bar.findChildren(QPushButton)
        assert pane.ai_speaker.text() == "源镜"
        assert "你好，我是源镜" in pane.assistant_bubble.text()
    finally:
        pane.deleteLater()


def test_suggestion_chip_sends_as_task_request(qt_app):
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        sent = []
        pane.task_requested.connect(lambda request, force: sent.append((request, force)))
        suggestion = pane.suggestion_buttons[0].text()
        pane.suggestion_buttons[0].click()
        assert sent == [(suggestion, False)]
    finally:
        pane.deleteLater()


def test_message_header_shows_agent_name(qt_app):
    from PySide6.QtWidgets import QLabel
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        container = pane._message_widgets({"role": "assistant", "content": "你好", "status": "complete", "agent": "audience"})[0]
        labels = [label.text() for label in container.findChildren(QLabel)]
        assert "受众分析师" in labels
        container = pane._message_widgets({"role": "user", "content": "提问", "status": "complete", "agent": ""})[0]
        labels = [label.text() for label in container.findChildren(QLabel)]
        assert "你" in labels
        container = pane._message_widgets({"role": "assistant", "content": "历史消息", "status": "complete", "agent": ""})[0]
        labels = [label.text() for label in container.findChildren(QLabel)]
        assert "源镜" in labels
    finally:
        pane.deleteLater()


def test_reasoning_panel_is_collapsed_until_clicked(qt_app):
    from scout.desktop.harness import ReasoningPanel
    panel = ReasoningPanel("第一步推理。\n第二步推理。", running=False)
    panel.show()
    try:
        assert not panel.expanded and not panel.area.isVisible()
        assert "思考过程" in panel.toggle.text()
        panel.toggle.click()
        assert panel.expanded and panel.area.isVisible()
        assert panel.area.toPlainText().startswith("第一步推理")
        panel.toggle.click()
        assert not panel.expanded and not panel.area.isVisible()
    finally:
        panel.close()


def test_continuation_appends_without_rebuilding_transcript(qt_app, ctx, monkeypatch):
    """同一会话续聊只追加新条目：已有气泡对象不被重建。"""
    import asyncio
    import json
    import scout.llm
    from scout.app import AppContext
    from scout.config import load_config
    from scout.llm import LLMReply
    from scout.store.conversation import Conversations
    from scout.desktop.window import MainWindow
    from scout.desktop.harness import SafeMessageBrowser

    class SlowClient:
        async def chat(self, system, user, **kwargs):
            await asyncio.sleep(0.5)
            return LLMReply(text=json.dumps({"reply": "好的。", "plan": None}, ensure_ascii=False), model="m")

    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: SlowClient())
    service = DesktopService(ctx.paths)
    service.save_settings("sk-test-never-sent", "test-model")
    window = MainWindow(service)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        history_ctx = AppContext.create(load_config(ctx.paths))
        conversations = Conversations(history_ctx.db)
        conversation_id = conversations.create("续聊")
        conversations.add(conversation_id, "user", "第一条历史消息")
        conversation = conversations.get(conversation_id)
        history_ctx.close()
        pane = window.enterprise
        pane.apply_conversation(conversation)

        def bubbles():
            return pane.transcript.findChildren(SafeMessageBrowser)

        first = bubbles()[0]
        pane.composer.setPlainText("接着聊一句")
        pane.generate_button.click()
        # 发送瞬间（模型仍在回复）：旧气泡原样保留，只追加了新的用户条目。
        assert first in bubbles()
        assert len(bubbles()) == 2
        pump(qt_app, lambda: not window.operations.busy and not window.pending and settled(window), timeout=10)
        assert len(bubbles()) == 3
        assert pane.conversation_data["messages"][-1]["content"] == "好的。"
    finally:
        window.close()


def test_chat_bubbles_refollow_viewport_width(qt_app, ctx):
    """窗口（或分栏）宽度变化后，聊天气泡重新换行并按内容重新定高。"""
    import time as _time
    from scout.desktop.window import MainWindow
    from scout.desktop.harness import SafeMessageBrowser
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        long_text = "这是一段用于验证响应式重排的较长文本。" * 40
        pane.apply_conversation({"id": 1, "title": "重排测试", "created_at": "2026-10-14 10:00",
                                 "messages": [{"role": "user", "content": long_text, "status": "complete"}]})
        bubbles = pane.transcript.findChildren(SafeMessageBrowser)
        assert len(bubbles) == 1
        wide_height = bubbles[0].height()
        assert wide_height > 65
        window.resize(1100, 800)
        deadline = _time.monotonic() + 2
        while _time.monotonic() < deadline and bubbles[0].height() <= wide_height:
            qt_app.processEvents()
            _time.sleep(0.01)
        assert bubbles[0].height() > wide_height
    finally:
        window.close()


def test_generate_button_turns_into_stop_and_cancels(qt_app, ctx, monkeypatch):
    """生成中按钮变"停止"：点击中断生成，已产生的思考过程保留。"""
    import asyncio
    import json
    import scout.llm
    from scout.llm import LLMReply
    from scout.desktop.window import MainWindow

    class SlowClient:
        async def chat(self, system, user, **kwargs):
            await asyncio.sleep(1.2)
            return LLMReply(text=json.dumps({"reply": "来不及了", "plan": None}, ensure_ascii=False), model="m")

    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: SlowClient())
    service = DesktopService(ctx.paths)
    service.save_settings("sk-test-never-sent", "test-model")
    window = MainWindow(service)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.composer.setPlainText("先停一下")
        pane.generate_button.click()
        assert pane.generate_button.text() == "停止"
        assert pane.generate_button.isEnabled()
        pane.generate_button.click()  # 停止生成
        pump(qt_app, lambda: settled(window), timeout=10)
        assert pane.generate_button.text() == "发送"
        assert pane.reasoning_panel is not None
        assert "停止" in pane.reasoning_panel.toggle.text()
    finally:
        window.close()


def test_message_hover_shows_copy_action(qt_app, ctx):
    """悬停消息块浮出复制按钮，点击复制内容到剪贴板。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    from scout.desktop.window import MainWindow

    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane.apply_conversation({"id": 1, "title": "工具条", "created_at": "2026-10-14 10:00",
                                 "messages": [{"role": "user", "content": "复制我", "status": "complete"}]})
        container = pane.transcript.findChild(QWidget, "messageBlock")
        assert container is not None
        toolbar = container.findChild(QWidget, "messageToolbar")
        assert toolbar is not None and not toolbar.isVisible()
        qt_app.sendEvent(container, QEvent(QEvent.Type.Enter))
        assert toolbar.isVisible()
        copy_button = container.findChild(QPushButton, "msgAction")
        copy_button.click()
        assert QApplication.clipboard().text() == "复制我"
        qt_app.sendEvent(container, QEvent(QEvent.Type.Leave))
        assert not toolbar.isVisible()
    finally:
        window.close()


def test_failed_message_retry_button_resends_last_request(qt_app, ctx, monkeypatch):
    """失败消息常驻"重试"按钮：点击后自动重发最近一条用户消息。"""
    import json
    import scout.llm
    from scout.llm import LLMReply
    from PySide6.QtWidgets import QPushButton
    from scout.desktop.window import MainWindow

    class FastClient:
        async def chat(self, system, user, **kwargs):
            return LLMReply(text=json.dumps({"reply": "重试后的回复", "plan": None}, ensure_ascii=False), model="m")

    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: FastClient())
    service = DesktopService(ctx.paths)
    service.save_settings("sk-test-never-sent", "test-model")
    window = MainWindow(service)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        pane._pending_messages = [{"role": "user", "content": "重试这个问题", "status": "pending"}]
        pane.show_chat_error("模拟失败：网络中断")
        retry = pane.transcript.findChild(QPushButton, "retryAction")
        assert retry is not None and retry.isVisible()
        retry.click()
        pump(qt_app, lambda: not window.operations.busy and not window.pending and settled(window), timeout=10)
        messages = pane.conversation_data["messages"]
        assert messages[-1]["role"] == "assistant" and "重试后的回复" in messages[-1]["content"]
    finally:
        window.close()


def test_chat_scroll_follows_and_pauses(qt_app, ctx):
    """用户向上查看时暂停跟随并显示"回到底部"；点击后恢复跟随。"""
    from scout.desktop.window import MainWindow

    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        long_text = "用于制造滚动空间的较长内容。" * 30
        messages = [{"role": "user", "content": long_text, "status": "complete"} for _ in range(6)]
        pane.apply_conversation({"id": 1, "title": "滚动", "created_at": "2026-10-14 10:00", "messages": messages})
        bar = pane.chat_scroll.verticalScrollBar()
        pump(qt_app, lambda: bar.maximum() > 100)
        bar.setValue(bar.maximum() // 2)
        qt_app.processEvents()
        assert not pane._follow
        assert pane.scroll_float.isVisible()
        pane.scroll_float.click()
        pump(qt_app, lambda: pane._follow and not pane.scroll_float.isVisible() and bar.value() == bar.maximum(), timeout=3)
    finally:
        window.close()


def test_composer_grows_and_shrinks(qt_app, ctx):
    """输入框高度随内容自适应（单行起步、封顶、清空回落）。"""
    from scout.desktop.window import MainWindow

    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        composer = window.enterprise.composer
        assert composer.maximumHeight() == 52
        composer.setPlainText("一\n二\n三\n四\n五")
        qt_app.processEvents()
        assert 52 < composer.maximumHeight() <= 150
        composer.setPlainText("\n".join(str(index) for index in range(40)))
        qt_app.processEvents()
        assert composer.maximumHeight() == 150
        composer.clear()
        qt_app.processEvents()
        assert composer.maximumHeight() == 52
    finally:
        window.close()
