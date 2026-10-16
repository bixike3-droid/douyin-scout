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
    from test_workflow import WorkflowClient
    client = WorkflowClient()
    monkeypatch.setattr(scout.llm, "DeepSeekClient", lambda cfg: client)
    window = MainWindow(service)
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        pane = window.enterprise
        request = "仅用已有数据，生成周末散客的传播方案"
        pane.composer.setPlainText(request)
        QTest.keyClick(pane.composer, Qt.Key.Key_Return)
        pump(qt_app, lambda: pane.current_report is not None and settled(window))
        assert client.calls[0][1]["context"]["evidence"][0]["data"]["request"] == request
        assert window.recent_tasks.count() == 2  # Conversation and its report.
        assert pane.workflow_card.run["status"] == "partial"
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
    assert window.nav.currentRow() == 6
    assert window.settings_tabs.currentIndex() == 1
    original = window.geometry()
    window.title_bar.toggle_maximized()
    assert window.isMaximized()
    window.title_bar.toggle_maximized()
    assert not window.isMaximized()
    assert window.geometry() == original  # 还原回小窗尺寸，而不是停在最大化矩形
    window.close()
    pump(qt_app, lambda: not window.isVisible())


def test_window_controls_are_standard_visible_buttons(qt_app, ctx):
    """窗口键固定在标题栏右侧：最小化 / 最大化 / 关闭，尺寸与文字保持可见。"""
    from PySide6.QtWidgets import QPushButton
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        bar = window.title_bar
        controls = bar.findChildren(QPushButton, "windowControl")
        close_button = bar.findChild(QPushButton, "closeControl")
        assert len(controls) == 2 and close_button is not None
        assert [button.text() for button in controls] == ["—", "□"]
        assert close_button.text() == "×"
        for button in (*controls, close_button):
            assert button.isVisible() and button.toolTip()
            assert button.width() >= 40 and button.height() >= 40  # 不再是缩水的小圆点
        center = close_button.mapTo(bar, close_button.rect().center())
        assert center.x() > bar.width() / 2  # 三键固定在右端标准位置
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_window_edge_hit_returns_resize_edges(qt_app, ctx):
    """窗口边缘 6px 是缩放带：命中返回对应边，中央不命中。"""
    from PySide6.QtCore import QPoint, Qt
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        top_left = window.mapToGlobal(QPoint(1, 1))
        assert window._hit_edges(top_left) == (Qt.Edge.LeftEdge | Qt.Edge.TopEdge)
        right_mid = window.mapToGlobal(QPoint(window.width() - 2, window.height() // 2))
        assert window._hit_edges(right_mid) == Qt.Edge.RightEdge
        center = window.mapToGlobal(QPoint(window.width() // 2, window.height() // 2))
        assert window._hit_edges(center) is None
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_maximize_toggle_prefers_system_command_only_on_real_windows(qt_app, ctx):
    """离屏 / 测试环境不碰系统命令，回退为 Qt 瞬时切换；状态照常翻转。"""
    from scout.desktop import harness
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        assert harness.try_system_toggle(window) is False  # 离屏平台不调 ctypes
        assert not window.isMaximized()
        window.title_bar.toggle_maximized()
        assert window.isMaximized()
        window.title_bar.toggle_maximized()
        assert not window.isMaximized()
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


def test_benchmark_page_lists_accounts_and_adds_from_link(qt_app, ctx):
    """第 6 个导航位是对标账号页：粘贴链接添加后出现在名单与详情里。"""
    from scout.desktop.window import MainWindow
    window = MainWindow(DesktopService(ctx.paths))
    window.show()
    try:
        pump(qt_app, lambda: window.initialized and settled(window))
        window.nav.setCurrentRow(5)
        pump(qt_app, lambda: settled(window))
        assert window.stack.currentWidget() is window.benchmark
        assert "对标" in window.heading.text()
        uid = "MS4wLjABAAAAtestpage000000000001"
        window._add_benchmark(f"https://www.douyin.com/user/{uid}")
        pump(qt_app, lambda: settled(window) and len(window.benchmark.accounts) == 1)
        assert window.benchmark.accounts_list.count() == 1
        assert uid in window.benchmark.detail_meta.text()
    finally:
        window.close()
        pump(qt_app, lambda: not window.isVisible())


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


def test_confirmation_card_requires_user_choice(qt_app):
    from PySide6.QtWidgets import QLabel
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        answered = []
        pane.confirmation_answered.connect(lambda rid, ok: answered.append((rid, ok)))
        pane.show_confirmation({"request_id": "r1", "tool": "collect", "name": "开始采集",
                                "agent": "data", "detail": '{"kinds": "quick"}'})
        card = pane._confirmation_cards["r1"]
        labels = " ".join(label.text() for label in card.findChildren(QLabel))
        assert "数据管家" in labels and "开始采集" in labels
        assert card.allow.isEnabled() and card.deny.isEnabled()
        card.allow.click()
        assert answered == [("r1", True)]
        assert not card.allow.isEnabled() and not card.deny.isEnabled()   # 点过之后按钮锁死
        card.deny.click()
        assert answered == [("r1", True)]                                  # 第二次点击无效
        pane.resolve_confirmation({"request_id": "r1", "approved": True})
        assert "已允许" in card.state.text()
    finally:
        pane.deleteLater()


def test_confirmation_card_marks_timeout_without_click(qt_app):
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        pane.show_confirmation({"request_id": "r2", "tool": "collect", "name": "开始采集", "agent": "data"})
        card = pane._confirmation_cards["r2"]
        pane.resolve_confirmation({"request_id": "r2", "approved": False})
        assert not card.allow.isEnabled() and "未确认" in card.state.text()
    finally:
        pane.deleteLater()


def test_right_tabs_are_hot_plan_canvas(qt_app):
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        assert [pane.right_tabs.tabText(i) for i in range(3)] == ["抖音热点", "内容方案", "可视化"]
        assert "自动生成" in pane.canvas_panel.hint.text()
    finally:
        pane.deleteLater()


def test_hot_panel_marks_and_click_sends_task(qt_app):
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        requests = []
        pane.task_requested.connect(lambda content, want_plan: requests.append(content))
        pane.hot_panel.apply({"topics": [
            {"word": "乡村振兴", "heat": 123, "mark": "可用", "why": "贴合文旅"},
            {"word": "明星绯闻", "heat": 99, "mark": "无关", "why": "损伤调性"},
        ], "usable": 1, "note": "", "fetched_at": "2026-10-15T12:00:00Z"})
        assert "可用 1 条" in pane.hot_panel.status.text()
        assert len(pane.hot_panel._rows) == 2
        first = pane.hot_panel._rows[0]
        first.clicked.emit(first.topic)
        assert requests and "乡村振兴" in requests[0] and "借势" in requests[0]
    finally:
        pane.deleteLater()


def test_hot_panel_error_state(qt_app):
    from scout.desktop.harness import HarnessPage
    pane = HarnessPage()
    try:
        pane.hot_panel.apply({"error": "热点获取失败：RuntimeError：没登录"})
        assert "热点获取失败" in pane.hot_panel.status.text()
        pane.hot_panel.set_loading()
        assert not pane.hot_panel.refresh_button.isEnabled()
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
            return LLMReply(text=json.dumps({"speaker": "steward"}), model="m")

        async def chat_messages(self, system, messages, **kwargs):
            await asyncio.sleep(0.5)
            return LLMReply(text="好的。", model="m")

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
            return LLMReply(text=json.dumps({"speaker": "steward"}), model="m")

        async def chat_messages(self, system, messages, **kwargs):
            await asyncio.sleep(1.2)
            return LLMReply(text="来不及了", model="m")

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
            return LLMReply(text=json.dumps({"speaker": "steward"}), model="m")

        async def chat_messages(self, system, messages, **kwargs):
            return LLMReply(text="重试后的回复", model="m")

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
