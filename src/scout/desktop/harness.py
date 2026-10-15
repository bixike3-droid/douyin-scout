"""Yuanjing's three-column task workspace, backed by the enterprise service."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QPropertyAnimation, QEasingCurve, QObject, QRunnable, QThreadPool, Slot
from PySide6.QtGui import QTextBlockFormat, QTextCursor, QPixmap
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QPushButton, QPlainTextEdit,
    QScrollArea, QTabWidget, QSplitter, QDialog, QTextBrowser, QSizePolicy, QLabel)
from ..analyze.agents import DEFAULT_AGENT_ID, TEAM, get as get_agent
from .enterprise import EnterprisePage, report_time
from .components import text
from .motion import ActivityDot, Disclosure, fade_in
from .theme import agent_badge, icon
from .diagrams import extract_mermaid_blocks, render_png, strip_mermaid_blocks


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


class ReasoningPanel(QFrame):
    """思维链面板：默认折叠，点击标题行展开；等待时显示活动点，可回看完整推理。"""

    def __init__(self, content="", *, running=True, motion=True, expanded=False):
        super().__init__()
        self.setObjectName("reasoningPanel")
        self.expanded = expanded
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(7)
        header = QHBoxLayout()
        header.setSpacing(9)
        self.dot = ActivityDot()
        self.dot.set_motion(motion)
        self.dot.set_running(running)
        header.addWidget(self.dot)
        self.toggle = QPushButton()
        self.toggle.setObjectName("reasoningToggle")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip("展开或收起思考过程")
        self.toggle.clicked.connect(self.flip)
        self._set_title("正在思考…" if running else "思考过程")
        header.addWidget(self.toggle)
        header.addStretch()
        self.hint = text("点击收起" if expanded else "点击展开", "muted")
        header.addWidget(self.hint)
        layout.addLayout(header)
        self.area = QPlainTextEdit()
        self.area.setObjectName("reasoningText")
        self.area.setReadOnly(True)
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.area)
        if content:
            self.area.setPlainText(content)
        self._apply_expanded()
        if not running:
            self.finish()

    def _set_title(self, value):
        self.toggle.setText(value + "    ›")

    def _content_height(self):
        line = max(14, self.area.fontMetrics().lineSpacing())
        return int(min(300, max(46, self.area.document().blockCount() * line + 14)))

    def flip(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self._apply_expanded(scroll_to_end=True)

    def _apply_expanded(self, *, scroll_to_end=False):
        self.area.setVisible(self.expanded)
        self.hint.setText("点击收起" if self.expanded else "点击展开")
        if self.expanded:
            self.area.setFixedHeight(self._content_height())
            if scroll_to_end:
                bar = self.area.verticalScrollBar()
                bar.setValue(bar.maximum())

    def append(self, delta):
        self.area.moveCursor(QTextCursor.MoveOperation.End)
        self.area.insertPlainText(delta)
        if self.expanded:
            self.area.setFixedHeight(self._content_height())
            bar = self.area.verticalScrollBar()
            bar.setValue(bar.maximum())

    def mark_answering(self):
        if self.dot.running:
            self._set_title("正在撰写回复…")

    def finish(self, stopped=False):
        self.dot.set_running(False)
        if self.toggle.text().startswith("正在"):
            self._set_title("思考已停止" if stopped else "思考过程")

    def relayout(self):
        if self.expanded:
            self.area.setFixedHeight(self._content_height())

    def set_motion(self, enabled):
        self.dot.set_motion(enabled)


class Composer(QPlainTextEdit):
    submitted = Signal()
    MIN_HEIGHT = 52
    MAX_HEIGHT = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        # 高度随内容行数自适应（约 1 到 7 行），超过后在框内滚动。
        self.document().documentLayout().documentSizeChanged.connect(self._fit_height)
        self.textChanged.connect(self._fit_height)
        self._fit_height()

    def _fit_height(self, *args):
        lines = max(1, int(self.document().size().height()))
        height = lines * self.fontMetrics().lineSpacing() + 12
        self.setFixedHeight(max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, height)))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            # Let an input method commit its pre-edit text before submitting.
            if self.inputMethodQuery(Qt.InputMethodQuery.ImEnabled) and getattr(self, "composing", False):
                super().keyPressEvent(event)
            else:
                self.submitted.emit()
            return
        super().keyPressEvent(event)

    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)


class ConfirmationCard(QFrame):
    """工具执行前的用户确认卡：出现在对话流里，允许或拒绝由用户点。"""

    answered = Signal(str, bool)

    def __init__(self, event):
        super().__init__()
        self.setObjectName("confirmCard")
        self.request_id = str(event.get("request_id") or "")
        member = get_agent(event.get("agent"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title = QLabel(f"「{member.name}」想执行「{event.get('name') or event.get('tool')}」，需要你确认")
        title.setObjectName("confirmTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        detail = str(event.get("detail") or "").strip()
        if detail:
            hint = text(f"参数：{detail}", "muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.allow = QPushButton("允许")
        self.allow.setObjectName("primary")
        self.allow.setCursor(Qt.CursorShape.PointingHandCursor)
        self.allow.clicked.connect(lambda: self._decide(True))
        self.deny = QPushButton("拒绝")
        self.deny.setObjectName("retryAction")
        self.deny.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deny.clicked.connect(lambda: self._decide(False))
        row.addWidget(self.allow)
        row.addWidget(self.deny)
        row.addStretch()
        self.state = text("", "muted")
        row.addWidget(self.state)
        layout.addLayout(row)

    def _decide(self, approved):
        if not self.allow.isEnabled():
            return
        self.allow.setEnabled(False)
        self.deny.setEnabled(False)
        self.state.setText("已允许，执行中…" if approved else "已拒绝")
        self.answered.emit(self.request_id, approved)

    def mark_resolved(self, approved):
        """执行端回执：用户已点过则保留其选择文案；超时等情况补一个说明。"""
        self.allow.setEnabled(False)
        self.deny.setEnabled(False)
        if not self.state.text():
            self.state.setText("已允许" if approved else "未确认（拒绝或超时），未执行")


class _DiagramWorker(QRunnable):
    """后台渲染 mermaid → PNG（本地 Chromium 优先，kroki 兜底）。"""

    class Signals(QObject):
        finished = Signal(object)

    def __init__(self, code):
        super().__init__()
        self.code = code
        self.signals = self.Signals()

    @Slot()
    def run(self):
        try:
            path = render_png(self.code)
        except Exception:
            path = None
        self.signals.finished.emit(path)


class DiagramView(QFrame):
    """对话里的可视化卡片：mermaid 渲染成图片展示，可复制源码。"""

    def __init__(self, code):
        super().__init__()
        self.setObjectName("diagramCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(text("AI 可视化", "muted"))
        header.addStretch()
        copy_button = QPushButton("复制源码")
        copy_button.setObjectName("linkButton")
        copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(code))
        header.addWidget(copy_button)
        layout.addLayout(header)
        self.image = QLabel("正在生成可视化…")
        self.image.setObjectName("diagramImage")
        self.image.setWordWrap(True)
        layout.addWidget(self.image)
        worker = _DiagramWorker(code)
        worker.signals.finished.connect(self._done)
        QThreadPool.globalInstance().start(worker)
        self._worker = worker

    def _done(self, path):
        if path is None:
            self.image.setText("可视化生成失败（本地渲染与在线兜底都不可用）")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.image.setText("可视化文件读取失败")
            return
        target = pixmap.scaledToWidth(min(pixmap.width(), 1040), Qt.TransformationMode.SmoothTransformation)
        target.setDevicePixelRatio(2)
        self.image.setText("")
        self.image.setPixmap(target)


MARK_COLORS = {
    "可用": ("#17351F", "#7BE3A0"),
    "参考": ("#3A2F14", "#F2C46D"),
    "无关": ("#2A303C", "#98A2B3"),
}


class HotTopicRow(QFrame):
    """一条热点：标记徽章 + 标题 + AI 评估理由；点击后交给团队拆解。"""

    clicked = Signal(dict)

    def __init__(self, index, topic):
        super().__init__()
        self.topic = topic
        self.setObjectName("hotRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        rank = QLabel(str(index))
        rank.setObjectName("hotRank")
        rank.setFixedWidth(20)
        rank.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(rank)
        mark = str(topic.get("mark") or "")
        badge = QLabel(mark or "待评估")
        background, foreground = MARK_COLORS.get(mark, ("#2A303C", "#8B93A3"))
        badge.setStyleSheet(f"background:{background};color:{foreground};border-radius:7px;"
                            "padding:2px 8px;font-weight:600;font-size:11px;")
        badge.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(badge)
        info = QVBoxLayout()
        info.setSpacing(2)
        word = text(str(topic.get("word") or ""), "bodyText")
        info.addWidget(word)
        why = str(topic.get("why") or "").strip()
        if why:
            info.addWidget(text(why, "muted"))
        layout.addLayout(info, 1)
        heat = topic.get("heat")
        if heat:
            heat_label = text(str(heat), "muted")
            heat_label.setAlignment(Qt.AlignmentFlag.AlignTop)
            layout.addWidget(heat_label)
        self.setToolTip((why + "\n" if why else "") + "点击：让团队拆解这个热点")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.topic)


class HotBoardPanel(QWidget):
    """右侧「抖音热点」：自动获取 + AI 可用性标记 + 点击交给团队拆解。"""

    topic_clicked = Signal(str)
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self.loaded_once = False
        self._rows: list[HotTopicRow] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.summary = text("打开程序会自动获取一次；点一条热点让团队拆解。", "muted")
        header.addWidget(self.summary, 1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("linkButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        self.status = text("", "muted")
        layout.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, 6, 0)
        self.body_layout.setSpacing(8)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self._placeholder("尚未获取热点榜")

    def _clear(self):
        self._rows = []
        clear_layout(self.body_layout)

    def _placeholder(self, message):
        self._clear()
        self.body_layout.addWidget(text(message, "muted"))
        self.body_layout.addStretch()

    def set_loading(self):
        self.status.setText("正在获取抖音实时热点并评估可用性…（首次会打开一次采集浏览器）")
        self.refresh_button.setEnabled(False)
        self._placeholder("获取中…")

    def apply(self, data):
        self.loaded_once = True
        self.refresh_button.setEnabled(True)
        if not isinstance(data, dict) or data.get("error"):
            message = (data or {}).get("error") if isinstance(data, dict) else "获取失败"
            self.status.setText(str(message or "获取失败"))
            self._placeholder("点右上角「刷新」重试")
            return
        topics = data.get("topics") or []
        self._clear()
        if not topics:
            self.status.setText("榜单为空")
            self._placeholder("点右上角「刷新」重试")
            return
        for index, topic in enumerate(topics, 1):
            row = HotTopicRow(index, topic)
            row.clicked.connect(self._on_row)
            self.body_layout.addWidget(row)
            self._rows.append(row)
        self.body_layout.addStretch()
        note = data.get("note") or ""
        stamp = str(data.get("fetched_at") or "")[11:16]
        parts = [f"共 {len(topics)} 条", f"AI 判定可用 {data.get('usable', 0)} 条"]
        if stamp:
            parts.append(stamp)
        self.status.setText(" · ".join(parts) + (f"（{note}）" if note else ""))

    def _on_row(self, topic):
        word = str(topic.get("word") or "").strip()
        if not word:
            return
        heat = topic.get("heat")
        request = (f"借势分析抖音热点：「{word}」" + (f"（当前热度 {heat}）" if heat else "")
                   + "。结合我们账号的实际情况：拆解它为什么火、我们能不能借势、如果能请给 2-3 个具体可执行的选题。")
        self.topic_clicked.emit(request)


class CanvasPanel(QWidget):
    """右侧「可视化」：展示 AI 在对话里最新生成的一张图。"""

    def __init__(self):
        super().__init__()
        self.current_code = ""
        self._worker = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.hint = text("团队在分析里自动生成的流程图、时间线、对比图会显示在这里；"
                         "也可以直接对团队说：「画个流程示意图」。", "muted")
        header.addWidget(self.hint, 1)
        self.copy_button = QPushButton("复制源码")
        self.copy_button.setObjectName("linkButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.current_code))
        header.addWidget(self.copy_button)
        layout.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 6, 0)
        self.image = QLabel("")
        self.image.setWordWrap(True)
        self.image.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        body_layout.addWidget(self.image)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

    def show_diagram(self, code):
        code = (code or "").strip()
        if not code or code == self.current_code:
            return
        self.current_code = code
        self.hint.setText("正在生成可视化…")
        self.copy_button.setEnabled(True)
        worker = _DiagramWorker(code)
        worker.signals.finished.connect(self._done)
        self._worker = worker
        QThreadPool.globalInstance().start(worker)

    def _done(self, path):
        if path is None:
            self.hint.setText("可视化生成失败（本地渲染与在线兜底都不可用）")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.hint.setText("可视化文件读取失败")
            return
        target = pixmap.scaledToWidth(min(pixmap.width(), 720), Qt.TransformationMode.SmoothTransformation)
        target.setDevicePixelRatio(2)
        self.image.setPixmap(target)
        self.hint.setText("最新一张 · 团队分析时自动生成")


class HarnessPage(EnterprisePage):
    confirmation_answered = Signal(str, bool)
    hot_refresh_requested = Signal()
    navigate_requested = Signal(str)
    task_requested = Signal(str, bool)
    cancel_requested = Signal()
    history_changed = Signal(object)
    report_selected = Signal(int)
    conversation_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.motion_enabled = True
        self.new_task_mode = True
        self.processing = False
        self.workspace_data = None
        # 气泡的换行宽度与高度依赖视口宽度；窗口/分栏尺寸变化后合并重排一次。
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.setInterval(30)
        self._bubble_timer.timeout.connect(self._relayout_bubbles)
        self.conversation_id = None
        self.conversation_data = None
        self.forms_dialog = None
        self.reasoning_panel = None
        # 待用户确认的工具卡：request_id → 卡片控件
        self._confirmation_cards: dict = {}
        # 已渲染到对话流里的消息条数；同会话续聊时据此只追加新条目，不整块重建。
        self._rendered_count = 0
        self._scroll_animation = None
        # 是否跟随新内容滚动；用户向上查看历史时暂停跟随。
        self._follow = True
        # Retain the existing native editors and their persistence connections.
        # The forms live in a dialog; the report editor is moved into the right pane.
        self.hidden_controls = QWidget(self)
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().setParent(self.hidden_controls)
        self.hidden_controls.hide()
        self.tabs.setTabVisible(1, False)
        self.generate_button.clicked.disconnect()
        self.generate_button.clicked.connect(self._on_generate)
        self.generate_button.setText("发送")
        self.generate_button.setIcon(icon("send", "#FFFFFF", 19))
        self.generate_button.setFixedWidth(82)
        self.generate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_workspace()

    def _build_workspace(self):
        self.layout().setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.layout().addWidget(self.splitter)
        center = QWidget()
        center.setObjectName("conversationPane")
        center.setMinimumWidth(410)
        main = QVBoxLayout(center)
        main.setContentsMargins(20, 20, 20, 14)
        main.setSpacing(14)
        self.task_title = text("新任务", "taskHeading")
        self.task_title.setMaximumHeight(60)
        main.addWidget(self.task_title)
        self.task_date = text("把你要解决的问题说给团队，合适的同事会来接手。", "muted")
        main.addWidget(self.task_date)
        # 团队一览：一条消息全队可见，由团队自动派单，不需要手动选人。
        self.step_labels = []
        self.agent_bar = QWidget()
        bar_layout = QGridLayout(self.agent_bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setHorizontalSpacing(14)
        bar_layout.setVerticalSpacing(7)
        for index, member in enumerate(TEAM):
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(7)
            badge = QLabel()
            badge.setObjectName("agentAvatar")
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setPixmap(agent_badge(member.color, member.icon, 26).pixmap(26, 26))
            cell_layout.addWidget(badge)
            cell_layout.addWidget(text(member.name, "agentName"))
            cell.setToolTip(member.name + " · " + member.role)
            bar_layout.addWidget(cell, index // 3, index % 3, Qt.AlignmentFlag.AlignLeft)
        main.addWidget(self.agent_bar)
        scroll = QScrollArea()
        self.chat_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.viewport().installEventFilter(self)
        scroll.verticalScrollBar().valueChanged.connect(self._on_chat_scrolled)
        self.scroll_float = QPushButton("回到底部", scroll.viewport())
        self.scroll_float.setObjectName("scrollBottom")
        self.scroll_float.setIcon(icon("arrowDown", "#C7D0E2", 15))
        self.scroll_float.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scroll_float.clicked.connect(self._jump_to_bottom)
        self.scroll_float.hide()
        body = QWidget()
        body.setObjectName("conversationBody")
        flow = QVBoxLayout(body)
        flow.setContentsMargins(0, 8, 0, 0)
        flow.setSpacing(10)
        ai_header = QHBoxLayout()
        self.ai_avatar = QLabel()
        self.ai_avatar.setObjectName("agentAvatar")
        self.ai_avatar.setFixedSize(34, 34)
        self.ai_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ai_header.addWidget(self.ai_avatar)
        self.activity = ActivityDot()
        ai_header.addWidget(self.activity)
        self.ai_speaker = text("", "speaker")
        ai_header.addWidget(self.ai_speaker)
        self.ai_role = text("", "muted")
        ai_header.addWidget(self.ai_role)
        ai_header.addStretch()
        flow.addLayout(ai_header)
        self.assistant_bubble = text("", "assistantBubble")
        flow.addWidget(self.assistant_bubble)
        self.suggestion_row = QWidget()
        self.suggestion_layout = QHBoxLayout(self.suggestion_row)
        self.suggestion_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestion_layout.setSpacing(8)
        self.suggestion_buttons = []
        self.suggestion_layout.addStretch()
        flow.addWidget(self.suggestion_row)
        self.transcript = QWidget()
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(0, 0, 0, 0)
        self.transcript_layout.setSpacing(14)
        flow.addWidget(self.transcript)
        self.reply_status = text("", "muted")
        self.reply_status.hide()
        flow.addWidget(self.reply_status)
        self.stage_cards = []
        for index, (title, subtitle) in enumerate((("①  企业资料", "了解企业资源、产品与目标客群"),
                                                   ("②  作品复盘", "查看已关联作品与真实指标"),
                                                   ("③  选题建议", "基于企业资料与内容证据生成建议"),
                                                   ("④  人工复核", "核实事实、修改建议并保存人工稿"))):
            stage = Disclosure(title, subtitle, expanded=index == 0)
            self.stage_cards.append(stage)
            flow.addWidget(stage)
        self.company_summary = text("企业特色与推广产品尚未填写。", "bodyText")
        self.stage_cards[0].body_layout.addWidget(self.company_summary)
        edit = QPushButton("编辑企业资料  ›")
        edit.setObjectName("linkButton")
        edit.clicked.connect(lambda: self.open_forms(0))
        self.stage_cards[0].body_layout.addWidget(edit, alignment=Qt.AlignmentFlag.AlignLeft)
        self.works_summary = text("暂无已关联作品。", "bodyText")
        self.stage_cards[1].body_layout.addWidget(self.works_summary)
        row = QHBoxLayout()
        see = QPushButton("查看作品数据")
        see.clicked.connect(lambda: self.navigate_requested.emit("works"))
        metrics = QPushButton("补录后台指标")
        metrics.clicked.connect(lambda: self.open_forms(2))
        row.addWidget(see)
        row.addWidget(metrics)
        self.stage_cards[1].body_layout.addLayout(row)
        self.topics_summary = text("生成后将在右侧显示选题、内容优化与策略。", "bodyText")
        self.stage_cards[2].body_layout.addWidget(self.topics_summary)
        self.review_summary = text("暂无待复核报告。", "bodyText")
        self.stage_cards[3].body_layout.addWidget(self.review_summary)
        review = QPushButton("打开内容方案")
        review.clicked.connect(lambda: self.right_tabs.setCurrentIndex(1))
        self.stage_cards[3].body_layout.addWidget(review, alignment=Qt.AlignmentFlag.AlignLeft)
        flow.addStretch()
        scroll.setWidget(body)
        main.addWidget(scroll, 1)
        composer_box = QFrame()
        composer_box.setObjectName("composerBox")
        box = QVBoxLayout(composer_box)
        box.setContentsMargins(12, 9, 12, 9)
        box.setSpacing(6)
        self.composer = Composer()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText("对源镜团队说点什么…")
        self.composer.submitted.connect(self._generate)
        box.addWidget(self.composer)
        row = QHBoxLayout()
        self.force.hide()
        self.plan_button = QPushButton("生成方案")
        self.plan_button.setObjectName("linkButton")
        self.plan_button.clicked.connect(self._request_plan)
        row.addWidget(self.plan_button)
        row.addStretch()
        row.addWidget(self.generate_button)
        box.addLayout(row)
        main.addWidget(composer_box)
        main.addWidget(text("Enter 发送 · Shift + Enter 换行 · 团队会自动把任务交给最合适的人", "composerHint"))
        self.splitter.addWidget(center)
        right = QWidget()
        right.setObjectName("resultPane")
        right.setMinimumWidth(360)
        result_layout = QVBoxLayout(right)
        result_layout.setContentsMargins(18, 12, 18, 14)
        result_layout.setSpacing(12)
        self.right_tabs = QTabWidget()
        self.right_tabs.setObjectName("resultTabs")
        result_layout.addWidget(self.right_tabs, 1)
        self.plan_scroll = QScrollArea()
        self.plan_scroll.setWidgetResizable(True)
        self.plan_body = QWidget()
        self.plan_body.setObjectName("resultBody")
        self.plan_layout = QVBoxLayout(self.plan_body)
        self.plan_layout.setContentsMargins(0, 16, 0, 0)
        self.plan_layout.setSpacing(14)
        self.plan_scroll.setWidget(self.plan_body)
        self.hot_panel = HotBoardPanel()
        self.hot_panel.refresh_requested.connect(self.hot_refresh_requested)
        self.hot_panel.topic_clicked.connect(self._analyze_hot_topic)
        self.right_tabs.addTab(self.hot_panel, "抖音热点")
        self.right_tabs.addTab(self.plan_scroll, "内容方案")
        self.canvas_panel = CanvasPanel()
        self.right_tabs.addTab(self.canvas_panel, "可视化")
        # 旧「参考素材 / 人工稿」不再占标签，控件与逻辑保留在隐藏容器里
        self._legacy_pane = QWidget()
        legacy_layout = QVBoxLayout(self._legacy_pane)
        legacy_layout.setContentsMargins(0, 0, 0, 0)
        legacy_layout.addWidget(self.evidence)
        edit_pane = QWidget()
        edit_layout = QVBoxLayout(edit_pane)
        edit_layout.setContentsMargins(0, 12, 0, 0)
        edit_layout.addWidget(text("修改会保留原始建议。填写复核说明后保存。", "muted"))
        edit_layout.addWidget(self.editor, 1)
        edit_layout.addWidget(self.reason)
        edit_layout.addWidget(self.reviewed)
        legacy_layout.addWidget(edit_pane)
        self._legacy_pane.hide()
        result_layout.addWidget(self._legacy_pane)
        result_layout.addWidget(self.report_state)
        buttons = QHBoxLayout()
        self.modify_button = QPushButton("修改建议")
        self.modify_button.setVisible(False)   # 人工稿入口已收起（改为 AI 团队方向）
        buttons.addWidget(self.modify_button)
        self.save_revision_button.setVisible(False)
        buttons.addWidget(self.save_revision_button)
        self.export_button.setText("导出报告")
        self.export_button.setObjectName("primary")
        buttons.addWidget(self.export_button)
        result_layout.addLayout(buttons)
        self.splitter.addWidget(right)
        self.splitter.setSizes([720, 480])
        self._empty_plan()
        self._show_team_greeting()

    def _show_team_greeting(self):
        steward = get_agent(DEFAULT_AGENT_ID)
        self.ai_avatar.setPixmap(agent_badge(steward.color, steward.icon, 34).pixmap(34, 34))
        self.ai_speaker.setText(steward.name)
        self.ai_role.setText(steward.role)
        self.assistant_bubble.setText(steward.greeting)
        clear_layout(self.suggestion_layout)
        self.suggestion_buttons = []
        for suggestion in steward.suggestions:
            button = QPushButton(suggestion)
            button.setObjectName("suggestionChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, value=suggestion: self._use_suggestion(value))
            self.suggestion_layout.addWidget(button)
            self.suggestion_buttons.append(button)
        self.suggestion_layout.addStretch()

    def _use_suggestion(self, value):
        if self.processing:
            return
        self.composer.setPlainText(value)
        self._generate()

    def _empty_plan(self):
        clear_layout(self.plan_layout)
        self.plan_layout.addWidget(text("内容方案", "planHeading"))
        self.plan_layout.addWidget(text("完成资料确认并生成建议后，结果会显示在这里。", "muted"))
        frame = QFrame()
        frame.setObjectName("emptyPlan")
        frame.setMinimumHeight(280)
        layout = QVBoxLayout(frame)
        layout.addStretch()
        layout.addWidget(text("暂无内容方案", "emptyHeading"), alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text("等待本次传播任务", "muted"), alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.plan_layout.addWidget(frame)
        self.plan_layout.addStretch()

    def open_forms(self, index=0):
        if not getattr(self, "controls_enabled", True):
            self.notice.emit("请等待当前操作结束后编辑资料")
            return
        self.tabs.setCurrentIndex(index)
        owner = self.window()
        if hasattr(owner, "settings_tabs"):
            owner.settings_tabs.setCurrentIndex(1)
        self.navigate_requested.emit("settings")

    def _generate(self):
        request = self.composer.toPlainText().strip()
        if not request or len(request) > 6000:
            self.notice.emit("请填写本次需求（不超过6000字）")
            return
        self.task_requested.emit(request, False)

    def _request_plan(self):
        self.task_requested.emit("请根据当前对话和已保存的企业资料，生成完整传播方案。缺失事实列为待确认，不要编造。", True)

    def _on_generate(self):
        if self.processing:
            # 此按钮当前显示为"停止"：中断生成，已产生的思考过程保留可看。
            self.cancel_requested.emit()
            self.notice.emit("正在停止…")
            return
        self._generate()

    def _copy_message(self, content):
        QApplication.clipboard().setText(content or "")
        self.notice.emit("已复制到剪贴板")

    def _retry_last_request(self):
        messages = list(getattr(self, "_pending_messages", None) or [])
        if not messages and self.conversation_data:
            messages = list(self.conversation_data["messages"])
        users = [message for message in messages if message["role"] == "user"]
        if not users:
            self.notice.emit("没有可重试的消息")
            return
        self.task_requested.emit(users[-1]["content"], False)

    def new_task(self):
        if not self._discard_report_changes():
            return
        self.new_task_mode = True
        self.conversation_id = None
        self.conversation_data = None
        self.reasoning_panel = None
        self._rendered_count = 0
        clear_layout(self.transcript_layout)
        self.assistant_bubble.show()
        self.suggestion_row.show()
        for widget in (self.ai_avatar, self.ai_speaker, self.ai_role, self.activity):
            widget.show()
        for stage in self.stage_cards:
            stage.show()
        self.reply_status.hide()
        self.current_report = None
        self.report_dirty = False
        self.applying = True
        self.editor.clear()
        self.evidence.clear()
        self.reason.clear()
        self.reviewed.setChecked(False)
        self.report_select.setCurrentIndex(-1)
        self.applying = False
        self.task_title.setText("新任务")
        self.task_date.setText("把你要解决的问题说给团队，合适的同事会来接手。")
        self._show_team_greeting()
        self.topics_summary.setText("生成后将在右侧显示选题、内容优化与策略。")
        self.review_summary.setText("暂无待复核报告。")
        self.composer.clear()
        self._empty_plan()
        self.report_state.setText("等待新任务")
        self.right_tabs.setCurrentIndex(1)
        self.composer.setFocus()
        self._update_stages()

    def apply_workspace(self, data, *, saved=False):
        # A new draft should not auto-load the most recent historical report.
        reports = data["reports"]
        super().apply_workspace(data, saved=saved)
        if self.new_task_mode:
            self.report_select.blockSignals(True)
            self.report_select.setCurrentIndex(-1)
            self.report_select.blockSignals(False)
        self.workspace_data = data
        if saved and self.forms_dialog:
            self.forms_dialog.hide()
        profile = data["profile"]
        def short(value, limit=40):
            return value[:limit] + ("…" if len(value) > limit else "")
        self.company_summary.setText("\n".join(("企业：" + profile["name"], "文旅特色：" + short(profile["features"] or "待填写"),
            "推广产品：" + short(profile["offer"] or "待填写"), "目标客群：" + short(profile["audience"] or "待确认"),
            "资料来源：" + short(profile["source"] or "待填写", 42))))
        count = len(data["works"]) if profile["account_confirmed"] else 0
        self.works_summary.setText(f"已关联本人作品 {count} 条。缺失指标可按后台资料补录。" if count else "暂无已关联作品。确认账号关联后，作品才能用于企业分析。")
        entries = [{**r, "kind": "report"} for r in reports]
        entries += [{**c, "kind": "conversation", "created_at": c["updated_at"]} for c in data.get("conversations", [])]
        self.history_changed.emit(sorted(entries, key=lambda r: r["created_at"], reverse=True))
        self._update_stages()

    def apply_report(self, report):
        super().apply_report(report)
        self.new_task_mode = False
        company = report["input"]["evidence"][0]["data"]
        request = company.get("request") or company.get("goal") or "传播决策报告"
        if self.conversation_id is None:
            self.task_title.setText(request)
            self.task_date.setText("创建时间：" + report_time(report["created_at"]))
            self._render_messages([
                {"role": "user", "content": request, "status": "complete", "agent": ""},
                {"role": "assistant", "content": report["output"]["summary"], "status": "complete", "agent": DEFAULT_AGENT_ID},
            ])
        self.topics_summary.setText(f"已生成 {len(report['output']['topics'])} 个选题，内容与依据见右侧。")
        self.review_summary.setText("用户已复核，修改记录已保存。" if report["revisions"] and report["revisions"][-1]["reviewed"] else "建议已生成，等待人工核实事实与执行条件。")
        self._render_plan(report)
        self._update_stages()
        if self.conversation_id is None:
            self.report_selected.emit(report["id"])
        self.plan_body.setGraphicsEffect(None)

    def _render_plan(self, report):
        clear_layout(self.plan_layout)
        self.plan_layout.addWidget(text("传播内容计划", "planHeading"))
        self.plan_layout.addWidget(text("基于本次企业资料与作品证据；发布前请人工复核。", "muted"))
        if report["revisions"]:
            preview = QTextBrowser()
            preview.setOpenExternalLinks(False)
            preview.setOpenLinks(False)
            preview.setMarkdown(report["revisions"][-1]["content"])
            preview.setMinimumHeight(550)
            self.plan_layout.addWidget(preview)
        else:
            self.plan_layout.addWidget(text("一、推广思路", "sectionTitle"))
            self.plan_layout.addWidget(text(report["output"]["summary"], "bodyText"))
            self.plan_layout.addWidget(text("二、推荐选题", "sectionTitle"))
            for index, topic in enumerate(report["output"]["topics"]):
                panel = QFrame()
                panel.setObjectName("topicCard")
                layout = QVBoxLayout(panel)
                layout.setContentsMargins(14, 14, 14, 14)
                layout.setSpacing(10)
                layout.addWidget(text(f"{index + 1}   {topic['title']}", "topicTitle"))
                row = QHBoxLayout()
                placeholder = text("暂无素材", "materialPlaceholder")
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                placeholder.setFixedSize(94, 76)
                row.addWidget(placeholder, alignment=Qt.AlignmentFlag.AlignTop)
                row.addWidget(text("开头：" + topic["hook"] + "\n\n" + topic["outline"], "bodyText"), 1)
                layout.addLayout(row)
                layout.addWidget(text("渠道：" + topic["platform"] + "\n行动引导：" + topic["cta"], "bodyText"))
                source = text("依据与来源：" + " · ".join(topic["evidence_ids"]) + "\n待确认：" + topic["needs_confirmation"], "sourceCard")
                layout.addWidget(source)
                self.plan_layout.addWidget(panel)
            for key, title in (("optimization", "三、内容优化"), ("strategy", "四、传播策略")):
                self.plan_layout.addWidget(text(title, "sectionTitle"))
                for entry in report["output"][key]:
                    self.plan_layout.addWidget(text("• " + entry["text"] + "\n依据：" + " · ".join(entry["evidence_ids"]), "bodyText"))
        self.plan_layout.addWidget(text("待确认信息\n" + "\n".join(report["output"]["unknowns"]), "warningCard"))
        self.plan_layout.addStretch()

    def _update_stages(self, active=None):
        data = self.workspace_data
        profile = data["profile"] if data else {}
        complete = [bool(profile.get("features") and profile.get("offer") and profile.get("source")),
                    bool(profile.get("account_confirmed") and data and data["works"]), bool(self.current_report),
                    bool(self.current_report and self.current_report["revisions"] and self.current_report["revisions"][-1]["reviewed"])]
        for i, (badge, label) in enumerate(self.step_labels):
            selected = i == active or (active is None and i == (3 if self.current_report else 0))
            badge.setText("✓" if complete[i] and i != active else str(i + 1))
            badge.setProperty("active", selected)
            label.setProperty("active", selected)
            for widget in (badge, label):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def set_processing(self, busy, message=""):
        self.processing = busy
        self.activity.set_running(busy)
        if self.conversation_id is not None or self.conversation_data:
            self._set_reply_status(message or ("模型正在回复…" if busy else ""), busy or bool(message))
        elif message:
            self.assistant_bubble.setText(message)
        self.generate_button.setText("停止" if busy else "发送")
        self.generate_button.setIcon(icon("stop", "#FFFFFF", 17) if busy else icon("send", "#FFFFFF", 19))
        if not busy:
            self._update_stages()

    def phase(self, index, message):
        self.assistant_bubble.setText(message)
        self._update_stages(active=index)

    def set_motion(self, enabled):
        self.motion_enabled = enabled
        self.activity.set_motion(enabled)
        for stage in self.stage_cards:
            stage.set_motion(enabled)
        if self.reasoning_panel is not None:
            self.reasoning_panel.set_motion(enabled)
        if not enabled:
            fade_in(self.plan_body, False)

    def set_controls_enabled(self, enabled):
        self.controls_enabled = enabled
        for widget in (self.force, self.composer, self.save_profile_button,
                       self.save_revision_button, self.export_button, self.metrics_button, self.report_select,
                       self.reason, self.reviewed, self.agent_bar, self.suggestion_row, self.modify_button, self.plan_button):
            widget.setEnabled(enabled)
        # "处理中"的按钮此时是"停止"，即使全局禁用也要保持可点，用于中断生成。
        self.generate_button.setEnabled(enabled or self.processing)
        self.editor.setReadOnly(not enabled)
        if self.forms_dialog:
            self.forms_dialog.setEnabled(enabled)

    def append_pending(self, request):
        messages = list(self.conversation_data["messages"]) if self.conversation_data else []
        messages.append({"role": "user", "content": request, "status": "pending"})
        self._pending_messages = messages
        if self.transcript.isVisible() and self._rendered_count == len(messages) - 1:
            # 同一会话续聊：只追加新条目，长对话也不再整块重建。
            self._switch_to_transcript_view()
            for widget in self._message_widgets(messages[-1]):
                self.transcript_layout.addWidget(widget)
                widget.show()
            self._rendered_count = len(messages)
            self._scroll_chat_bottom(force=True)
        else:
            self._render_messages(messages)
        self.begin_reasoning()
        self.composer.clear()
        self._set_reply_status("等待模型回复…", True)

    def _set_reply_status(self, text, visible):
        was_visible = self.reply_status.isVisible()
        self.reply_status.setText(text)
        self.reply_status.setVisible(visible)
        if visible and not was_visible:
            fade_in(self.reply_status, self.motion_enabled)

    def begin_reasoning(self):
        """发送后立即在对话流里占位"正在思考…"，替代右下角进度条。"""
        self.abort_reasoning()
        self.reasoning_panel = ReasoningPanel(running=True, motion=self.motion_enabled)
        self.transcript_layout.addWidget(self.reasoning_panel)
        self.reasoning_panel.show()
        self._scroll_chat_bottom(force=True)

    def append_reasoning(self, delta):
        if not delta:
            return
        if self.reasoning_panel is None:
            self.begin_reasoning()
        self.reasoning_panel.append(str(delta))
        # 流式追加要跟手：直接贴底，不用平滑动画。
        self._scroll_chat_bottom(smooth=False)

    def mark_answering(self):
        if self.reasoning_panel is not None:
            self.reasoning_panel.mark_answering()

    def end_reasoning(self, stopped=False):
        if self.reasoning_panel is not None:
            self.reasoning_panel.finish(stopped=stopped)

    def abort_reasoning(self):
        """取消时移除未完成的思考面板（内容尚未入库）。"""
        if self.reasoning_panel is None:
            return
        self.reasoning_panel.hide()
        self.reasoning_panel.deleteLater()
        self.reasoning_panel = None

    def _scroll_chat_bottom(self, smooth=True, force=False):
        if not force and not self._follow:
            return
        bar = self.chat_scroll.verticalScrollBar()

        def start():
            target = bar.maximum()
            if not smooth or not self.motion_enabled:
                bar.setValue(target)
                return
            if bar.value() == target:
                return
            previous = self._scroll_animation
            if previous is not None:
                previous.stop()
            animation = QPropertyAnimation(bar, b"value", bar)
            animation.setStartValue(bar.value())
            animation.setEndValue(target)
            animation.setDuration(180)
            animation.finished.connect(lambda: bar.setValue(bar.maximum()) if self._follow else None)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._scroll_animation = animation
            animation.start()

        QTimer.singleShot(0, start)

    def _on_chat_scrolled(self, value):
        bar = self.chat_scroll.verticalScrollBar()
        # 接近底部（48px 内）视为跟随；用户向上查看时暂停跟随。
        self._follow = value >= bar.maximum() - 48
        self._update_scroll_float()

    def _update_scroll_float(self):
        bar = self.chat_scroll.verticalScrollBar()
        visible = not self._follow and bar.maximum() > 40
        self.scroll_float.setVisible(visible)
        if visible:
            viewport = self.chat_scroll.viewport()
            self.scroll_float.adjustSize()
            self.scroll_float.move(max(8, viewport.width() - self.scroll_float.width() - 18),
                                   max(8, viewport.height() - self.scroll_float.height() - 14))
            self.scroll_float.raise_()

    def _jump_to_bottom(self):
        self._follow = True
        self._scroll_chat_bottom(smooth=True, force=True)

    def eventFilter(self, watched, event):
        # 窗口拆除阶段可能收到残留事件并访问到已销毁对象，此时静默跳过。
        try:
            if watched is self.chat_scroll.viewport() and event.type() == QEvent.Type.Resize:
                # 对话区宽度变化（窗口缩放、分栏拖动）后：气泡重新换行、浮标重新定位。
                self._bubble_timer.start()
                self._update_scroll_float()
            elif isinstance(watched, QWidget) and watched.objectName() == "messageBlock":
                # 悬停消息块时浮出复制等操作；失败消息的工具条常驻。
                toolbar = watched.findChild(QWidget, "messageToolbar")
                if toolbar is not None and not toolbar.property("pinned"):
                    if event.type() == QEvent.Type.Enter:
                        toolbar.setVisible(True)
                    elif event.type() == QEvent.Type.Leave:
                        toolbar.setVisible(False)
        except RuntimeError:
            pass
        return super().eventFilter(watched, event)

    def _bubble_width(self):
        return max(280, self.chat_scroll.viewport().width() - 50)

    def _bubble_height(self, bubble):
        return max(65, int(bubble.document().size().height()) + 32)

    def _relayout_bubbles(self):
        for bubble in self.transcript.findChildren(SafeMessageBrowser):
            bubble.document().setTextWidth(self._bubble_width())
            bubble.setFixedHeight(self._bubble_height(bubble))
        for panel in self.transcript.findChildren(ReasoningPanel):
            panel.relayout()

    def apply_conversation(self, data):
        self.conversation_data = data
        self.conversation_id = data["id"]
        self.new_task_mode = False
        self.task_title.setText(data["title"])
        self.task_date.setText("对话创建：" + report_time(data["created_at"]))
        self._render_messages(data["messages"])
        self.reply_status.hide()
        self.conversation_selected.emit(data["id"])

    def _switch_to_transcript_view(self):
        self.transcript.show()
        for widget in (self.ai_avatar, self.ai_speaker, self.ai_role, self.activity):
            widget.hide()
        for stage in self.stage_cards:
            stage.hide()
        self.assistant_bubble.hide()
        self.suggestion_row.hide()

    def _message_widgets(self, message):
        """单条消息对应的控件：说话人行（含悬停工具条）、可选思考过程、正文气泡。"""
        role = message["role"]
        agent = get_agent(message.get("agent"))
        title = "你" if role == "user" else ("调用问题" if role == "error" else agent.name)
        container = QWidget()
        container.setObjectName("messageBlock")
        container.installEventFilter(self)
        block = QVBoxLayout(container)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        if role == "assistant":
            badge = QLabel()
            badge.setObjectName("agentAvatar")
            badge.setFixedSize(20, 20)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setPixmap(agent_badge(agent.color, agent.icon, 20).pixmap(20, 20))
            header.addWidget(badge)
        speaker = text(title, "speaker")
        if role == "assistant":
            speaker.setToolTip(agent.role)
        header.addWidget(speaker)
        header.addStretch()
        toolbar = QWidget()
        toolbar.setObjectName("messageToolbar")
        actions = QHBoxLayout(toolbar)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        copy_button = QPushButton()
        copy_button.setObjectName("msgAction")
        copy_button.setIcon(icon("copy", "#9AA6B8", 16))
        copy_button.setFixedSize(26, 26)
        copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_button.setToolTip("复制内容")
        copy_button.clicked.connect(lambda: self._copy_message(message["content"]))
        actions.addWidget(copy_button)
        pinned = role == "error"
        if pinned:
            # 失败消息的重试按钮常驻显示，无需悬停才能发现。
            retry_button = QPushButton("重试")
            retry_button.setObjectName("retryAction")
            retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
            retry_button.clicked.connect(self._retry_last_request)
            actions.addWidget(retry_button)
        toolbar.setProperty("pinned", pinned)
        toolbar.setVisible(pinned)
        header.addWidget(toolbar)
        block.addLayout(header)
        if role == "assistant" and (message.get("reasoning") or "").strip():
            block.addWidget(ReasoningPanel(message["reasoning"].strip(), running=False, motion=self.motion_enabled))
        bubble = SafeMessageBrowser()
        bubble.setOpenLinks(False)
        bubble.setOpenExternalLinks(False)
        diagram_codes = extract_mermaid_blocks(message["content"]) if role == "assistant" else []
        bubble_text = strip_mermaid_blocks(message["content"]) if diagram_codes else message["content"]
        bubble.setMarkdown(bubble_text)
        # Qt 样式表不支持 line-height；用块格式加行距，避免正文发紧。
        cursor = QTextCursor(bubble.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)
        bubble.setStyleSheet("background:#292F39;border-radius:9px;padding:12px;" if role == "user" else "background:#252B35;border-radius:9px;padding:12px;")
        bubble.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bubble.document().setTextWidth(self._bubble_width())
        bubble.setFixedHeight(self._bubble_height(bubble))
        block.addWidget(bubble)
        if diagram_codes:
            if not bubble_text.strip():
                bubble.hide()
            for code in diagram_codes[:2]:
                block.addWidget(DiagramView(code))
        return [container]

    def _render_messages(self, messages):
        self._switch_to_transcript_view()
        self.reasoning_panel = None
        clear_layout(self.transcript_layout)
        latest_code = ""
        for message in messages:
            for widget in self._message_widgets(message):
                self.transcript_layout.addWidget(widget)
                widget.show()
            if message.get("role") == "assistant":
                codes = extract_mermaid_blocks(message.get("content") or "")
                if codes:
                    latest_code = codes[-1]
        self._rendered_count = len(messages)
        self._scroll_chat_bottom(force=True)
        if self.motion_enabled:
            fade_in(self.transcript, True)
        if latest_code:
            self.canvas_panel.show_diagram(latest_code)

    def show_chat_error(self, message):
        messages = list(getattr(self, "_pending_messages", []))
        if not messages and self.conversation_data:
            messages = list(self.conversation_data["messages"])
        messages.append({"role": "error", "content": message, "status": "failed"})
        self._render_messages(messages)

    def show_confirmation(self, event):
        """工具执行前的确认卡：追加到对话流末尾，等用户点「允许 / 拒绝」。"""
        card = ConfirmationCard(event)
        card.answered.connect(self.confirmation_answered)
        self.transcript.show()
        self.transcript_layout.addWidget(card)
        card.show()
        if self.motion_enabled:
            fade_in(card, True)
        self._confirmation_cards[card.request_id] = card
        self._scroll_chat_bottom()

    def resolve_confirmation(self, event):
        """执行端回执：更新卡片状态（用户点过则不覆盖）。"""
        card = self._confirmation_cards.pop(str(event.get("request_id") or ""), None)
        if card is not None:
            card.mark_resolved(bool(event.get("approved")))

    def _analyze_hot_topic(self, request):
        """点热点：把拆解请求直接发给团队（走正常对话链路）。"""
        self.task_requested.emit(request, False)


class SafeMessageBrowser(QTextBrowser):
    def loadResource(self, resource_type, name):
        # Model text may contain image URLs; it is not permission to fetch files.
        return None


class TitleBar(QWidget):
    """Native system move and standard minimize/maximize/close controls."""
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setObjectName("titleBar")
        self.setFixedHeight(48)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(16, 0, 0, 0)
        self.row.setSpacing(12)
        self.brand = QPushButton("源镜 · 传播工作台")
        self.brand.setObjectName("linkButton")
        self.brand.setIcon(icon("sparkles", "#75D8BA", 26))
        self.brand.setStyleSheet("font-size:16px;color:#E4E9F3;")
        self.row.addWidget(self.brand)
        self.row.addStretch()

    def add_controls(self):
        for title, name, action in (("—", "最小化", self.owner.showMinimized),
                                    ("□", "最大化或还原", self.toggle_maximized),
                                    ("×", "关闭", self.owner.close)):
            button = QPushButton(title)
            button.setObjectName("closeControl" if title == "×" else "windowControl")
            button.setFixedSize(40, 48)
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.clicked.connect(action)
            self.row.addWidget(button)

    def toggle_maximized(self):
        self.owner.showNormal() if self.owner.isMaximized() else self.owner.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            self.owner.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
